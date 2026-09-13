# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from collections import defaultdict
from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.dependency_inference import (
    GoImportPathsMappingAddressSet,
    GoModuleImportPathsMapping,
    GoModuleImportPathsMappings,
    GoModuleImportPathsMappingsHook,
)
from pants.backend.go.target_types import GoModTarget, GoOwningGoModAddressField, GoPackageTarget
from pants.backend.go.testutil import gen_module_gomodproxy
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    build_pkg_target,
    first_party_pkg,
    go_mod,
    import_analysis,
    link,
    sdk,
    third_party_pkg,
)
from pants.backend.go.util_rules.build_opts import GoBuildOptions
from pants.backend.go.util_rules.build_pkg import (
    BuildGoPackageRequest,
    BuiltGoPackage,
    FallibleBuildGoPackageRequest,
    FallibleBuiltGoPackage,
)
from pants.backend.go.util_rules.build_pkg_stdlib import (
    BuildGoPackageRequestForStdlibRequest,
    setup_build_go_package_target_request_for_stdlib,
)
from pants.backend.go.util_rules.build_pkg_target import (
    BuildGoPackageTargetRequest,
    GoCodegenBuildRequest,
    setup_build_go_package_target_request,
)
from pants.backend.go.util_rules.build_pkg_third_party import (
    BuildGoPackageRequestForThirdPartyPackageRequest,
)
from pants.backend.go.util_rules.go_mod import OwningGoModRequest, find_owning_go_mod
from pants.backend.go.util_rules.import_analysis import (
    GoStdLibPackage,
    GoStdLibPackages,
    GoStdLibPackagesRequest,
)
from pants.core.target_types import FilesGeneratorTarget, FileSourceField, FileTarget
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, FileContent, Snapshot
from pants.engine.internals.graph import resolve_dependencies
from pants.engine.intrinsics import create_digest
from pants.engine.rules import QueryRule, concurrently, implicitly, rule
from pants.engine.target import AllTargets, Dependencies, DependenciesRequest
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import path_safe


# Set up a semi-complex codegen plugin. Note that we cyclically call into the
# `BuildGoPackageTargetRequest` rule to set up a dependency on a third-party package, as this
# is common for codegen plugins to need to do.
class GoCodegenBuildFilesRequest(GoCodegenBuildRequest):
    generate_from = FileSourceField


class GenerateFromFileImportPathsMappingHook(GoModuleImportPathsMappingsHook):
    pass


@rule(desc="Map import paths for all 'generate from file' targets.", level=LogLevel.DEBUG)
async def map_import_paths(
    _request: GenerateFromFileImportPathsMappingHook,
    all_targets: AllTargets,
) -> GoModuleImportPathsMappings:
    file_targets = [tgt for tgt in all_targets if tgt.has_field(FileSourceField)]

    owning_go_mod_targets = await concurrently(
        find_owning_go_mod(OwningGoModRequest(tgt.address), **implicitly()) for tgt in file_targets
    )

    import_paths_by_module: dict[Address, dict[str, set[Address]]] = defaultdict(
        lambda: defaultdict(set)
    )

    for owning_go_mod, tgt in zip(owning_go_mod_targets, file_targets):
        import_paths_by_module[owning_go_mod.address]["codegen.com/gen"].add(tgt.address)

    return GoModuleImportPathsMappings(
        FrozenDict(
            {
                go_mod_addr: GoModuleImportPathsMapping(
                    mapping=FrozenDict(
                        {
                            import_path: GoImportPathsMappingAddressSet(
                                addresses=tuple(sorted(addresses)), infer_all=True
                            )
                            for import_path, addresses in import_path_mapping.items()
                        }
                    ),
                    address_to_import_path=FrozenDict(
                        {
                            address: import_path
                            for import_path, addresses in import_path_mapping.items()
                            for address in addresses
                        }
                    ),
                )
                for go_mod_addr, import_path_mapping in import_paths_by_module.items()
            }
        )
    )


@rule
async def generate_from_file(request: GoCodegenBuildFilesRequest) -> FallibleBuildGoPackageRequest:
    content = dedent(
        """\
        package gen

        import "fmt"
        import "github.com/google/uuid"

        func Quote(s string) string {
            uuid.SetClockSequence(-1)  // A trivial line to use uuid.
            return fmt.Sprintf(">> %s <<", s)
        }
        """
    )
    digest = await create_digest(CreateDigest([FileContent("codegen/f.go", content.encode())]))

    deps = await resolve_dependencies(
        DependenciesRequest(request.target[Dependencies]), **implicitly()
    )
    assert len(deps) == 1
    assert deps[0].generated_name == "github.com/google/uuid"
    thirdparty_dep = await setup_build_go_package_target_request(
        BuildGoPackageTargetRequest(deps[0], build_opts=GoBuildOptions()), **implicitly()
    )
    assert thirdparty_dep.request is not None

    # The generated code imports `fmt` directly, so it must be declared as a direct
    # dependency: the compile sandbox/importcfg contains only direct deps' export data.
    fmt_dep = await setup_build_go_package_target_request_for_stdlib(
        BuildGoPackageRequestForStdlibRequest("fmt", build_opts=GoBuildOptions()),
        **implicitly(),
    )
    assert fmt_dep.request is not None

    return FallibleBuildGoPackageRequest(
        request=BuildGoPackageRequest(
            import_path="codegen.com/gen",
            pkg_name="gen",
            digest=digest,
            dir_path="codegen",
            build_opts=GoBuildOptions(),
            go_files=("f.go",),
            s_files=(),
            direct_dependencies=(fmt_dep.request, thirdparty_dep.request),
            minimum_go_version=None,
        ),
        import_path="codegen.com/gen",
    )


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *sdk.rules(),
            *assembly.rules(),
            *build_pkg.rules(),
            *build_pkg_target.rules(),
            *import_analysis.rules(),
            *link.rules(),
            *go_mod.rules(),
            *first_party_pkg.rules(),
            *third_party_pkg.rules(),
            *target_type_rules.rules(),
            generate_from_file,
            map_import_paths,
            QueryRule(BuiltGoPackage, [BuildGoPackageRequest]),
            QueryRule(FallibleBuiltGoPackage, [BuildGoPackageRequest]),
            QueryRule(BuildGoPackageRequest, [BuildGoPackageTargetRequest]),
            QueryRule(FallibleBuildGoPackageRequest, [BuildGoPackageTargetRequest]),
            QueryRule(GoStdLibPackages, (GoStdLibPackagesRequest,)),
            QueryRule(BuildGoPackageRequest, (BuildGoPackageRequestForStdlibRequest,)),
            QueryRule(BuildGoPackageRequest, (BuildGoPackageRequestForThirdPartyPackageRequest,)),
            UnionRule(GoCodegenBuildRequest, GoCodegenBuildFilesRequest),
            UnionRule(GoModuleImportPathsMappingsHook, GenerateFromFileImportPathsMappingHook),
            FileTarget.register_plugin_field(GoOwningGoModAddressField),
            FilesGeneratorTarget.register_plugin_field(GoOwningGoModAddressField),
        ],
        target_types=[
            GoModTarget,
            GoPackageTarget,
            FilesGeneratorTarget,
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def assert_built(
    rule_runner: RuleRunner, request: BuildGoPackageRequest, *, expected_import_paths: list[str]
) -> None:
    built_package = rule_runner.request(BuiltGoPackage, [request])
    own_files = rule_runner.request(Snapshot, [built_package.archive_digest]).files
    assert built_package.pkg_archive_path == os.path.join(
        "__pkgs__", path_safe(built_package.import_path), "__pkg__.a"
    )
    assert built_package.pkg_archive_path in own_files
    # Standard library dependencies may resolve to pre-built archives
    # (`__go_stdlib__/<import_path>.a`) instead of being compiled from source into the
    # `__pkgs__/...` layout, depending on `[golang].use_prebuilt_stdlib_archives` and build
    # options.
    expected = {
        import_path: (
            os.path.join("__pkgs__", path_safe(import_path), "__pkg__.a"),
            f"__go_stdlib__/{import_path}.a",
        )
        for import_path in expected_import_paths
    }
    actual = {
        import_path: archive_path
        for import_path, (archive_path, _) in built_package.transitive_pkg_archives.items()
    }
    for import_path, acceptable_archive_paths in expected.items():
        assert import_path in actual, f"expected {import_path} to be in build output"
        assert actual[import_path] in acceptable_archive_paths, (
            "expected package archive paths to match"
        )


def assert_pkg_target_built(
    rule_runner: RuleRunner,
    addr: Address,
    *,
    expected_import_path: str,
    expected_dir_path: str,
    expected_direct_dependency_import_paths: list[str],
    expected_transitive_dependency_import_paths: list[str],
    expected_go_file_names: list[str],
) -> None:
    build_request = rule_runner.request(
        BuildGoPackageRequest, [BuildGoPackageTargetRequest(addr, build_opts=GoBuildOptions())]
    )
    assert build_request.import_path == expected_import_path
    assert build_request.dir_path == expected_dir_path
    assert build_request.go_files == tuple(expected_go_file_names)
    assert not build_request.s_files
    assert sorted([dep.import_path for dep in build_request.direct_dependencies]) == sorted(
        expected_direct_dependency_import_paths
    )
    assert_built(
        rule_runner,
        build_request,
        expected_import_paths=[
            expected_import_path,
            *expected_direct_dependency_import_paths,
            *expected_transitive_dependency_import_paths,
        ],
    )


def test_build_first_party_pkg_target(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "go.mod": dedent(
                """\
                module example.com/greeter
                go 1.17
                """
            ),
            "greeter.go": dedent(
                """\
                package greeter

                import "fmt"

                func Hello() {
                    fmt.Println("Hello world!")
                }
                """
            ),
            "BUILD": "go_mod(name='mod')\ngo_package(name='pkg')",
        }
    )
    assert_pkg_target_built(
        rule_runner,
        Address("", target_name="pkg"),
        expected_import_path="example.com/greeter",
        expected_dir_path="",
        expected_go_file_names=["greeter.go"],
        expected_direct_dependency_import_paths=["fmt"],
        expected_transitive_dependency_import_paths=[],
    )


def test_build_third_party_pkg_target(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "go.mod": dedent(
                """\
                module example.com/greeter
                go 1.17
                require github.com/google/uuid v1.3.0
                """
            ),
            "go.sum": dedent(
                """\
                github.com/google/uuid v1.3.0 h1:t6JiXgmwXMjEs8VusXIJk2BXHsn+wx8BZdTaoZ5fu7I=
                github.com/google/uuid v1.3.0/go.mod h1:TIyPZe4MgqvfeYDBFedMoGGpEw/LqOeaOT+nhxU+yHo=
                """
            ),
            "BUILD": "go_mod(name='mod')",
        }
    )
    import_path = "github.com/google/uuid"
    assert_pkg_target_built(
        rule_runner,
        Address("", target_name="mod", generated_name=import_path),
        expected_import_path=import_path,
        expected_dir_path="gopath/pkg/mod/github.com/google/uuid@v1.3.0",
        expected_go_file_names=[
            "dce.go",
            "doc.go",
            "hash.go",
            "marshal.go",
            "node.go",
            "node_net.go",
            "null.go",
            "sql.go",
            "time.go",
            "util.go",
            "uuid.go",
            "version1.go",
            "version4.go",
        ],
        expected_direct_dependency_import_paths=[
            "bytes",
            "crypto/md5",
            "crypto/rand",
            "crypto/sha1",
            "database/sql/driver",
            "encoding/binary",
            "encoding/hex",
            "encoding/json",
            "errors",
            "fmt",
            "hash",
            "io",
            "net",
            "os",
            "strings",
            "sync",
            "time",
        ],
        expected_transitive_dependency_import_paths=[],
    )


def test_third_party_pkg_digest_is_sliced_to_package_sources(rule_runner: RuleRunner) -> None:
    import_path = "pantsbuild.org/go-slice-for-test"
    version = "v0.0.1"
    files = gen_module_gomodproxy(
        version,
        import_path,
        (
            ("pure/pure.go", "package pure\n\nfunc Two() int { return 2 }\n"),
            # Glob metacharacters in file names must not affect the slicing globs.
            ("pure/helpers[gen].go", "package pure\n"),
            ("other/other.go", "package other\n"),
            (
                "embedder/embedder.go",
                dedent(
                    """\
                    package embedder

                    import _ "embed"

                    //go:embed data/msg.txt
                    var Msg string
                    """
                ),
            ),
            ("embedder/data/msg.txt", "hello\n"),
            ("native/native.go", "package native\n\nfunc Two() int { return 2 }\n"),
            ("native/native.h", "#define TWO 2\n"),
        ),
    )
    files.update(
        {
            "BUILD": "go_mod(name='mod')",
            "go.mod": dedent(
                f"""\
                module example.com/slicetest
                go 1.17

                require {import_path} {version}
                """
            ),
        }
    )
    rule_runner.write_files(files)
    rule_runner.set_options(
        [
            f"--golang-subprocess-env-vars=GOPROXY=file://{rule_runner.build_root}/go-mod-proxy",
            "--golang-subprocess-env-vars=GOSUMDB=off",
        ],
        env_inherit={"PATH"},
    )

    prefix = f"gopath/pkg/mod/{import_path}@{version}"

    def get_build_request(pkg_import_path: str) -> BuildGoPackageRequest:
        return rule_runner.request(
            BuildGoPackageRequest,
            [
                BuildGoPackageTargetRequest(
                    Address("", target_name="mod", generated_name=pkg_import_path),
                    build_opts=GoBuildOptions(),
                )
            ],
        )

    def digest_files(request: BuildGoPackageRequest) -> set[str]:
        return set(rule_runner.request(Snapshot, [request.digest]).files)

    pure_request = get_build_request(f"{import_path}/pure")
    assert digest_files(pure_request) == {
        f"{prefix}/pure/pure.go",
        f"{prefix}/pure/helpers[gen].go",
    }

    embedder_request = get_build_request(f"{import_path}/embedder")
    assert digest_files(embedder_request) == {
        f"{prefix}/embedder/embedder.go",
        f"{prefix}/embedder/data/msg.txt",
    }

    # Native-code packages keep the whole module.
    native_files = digest_files(get_build_request(f"{import_path}/native"))
    assert f"{prefix}/other/other.go" in native_files

    # The sliced packages still compile.
    assert_built(rule_runner, pure_request, expected_import_paths=[f"{import_path}/pure"])
    assert_built(rule_runner, embedder_request, expected_import_paths=[f"{import_path}/embedder"])


def test_third_party_module_mode_digest_is_sliced_by_import_path(rule_runner: RuleRunner) -> None:
    # Under module granularity a module's non-root packages are built through the by-import-path rule
    # rather than a per-package target, so it must slice the same way the target path does.
    import_path = "pantsbuild.org/go-slice-for-test-module"
    version = "v0.0.1"
    files = gen_module_gomodproxy(
        version,
        import_path,
        (
            ("pure/pure.go", "package pure\n\nfunc Two() int { return 2 }\n"),
            ("pure/helpers[gen].go", "package pure\n"),
            ("other/other.go", "package other\n"),
            (
                "embedder/embedder.go",
                dedent(
                    """\
                    package embedder

                    import _ "embed"

                    //go:embed data/msg.txt
                    var Msg string
                    """
                ),
            ),
            ("embedder/data/msg.txt", "hello\n"),
            ("native/native.go", "package native\n\nfunc Two() int { return 2 }\n"),
            ("native/native.h", "#define TWO 2\n"),
        ),
    )
    files.update(
        {
            "BUILD": "go_mod(name='mod')",
            "go.mod": dedent(
                f"""\
                module example.com/slicetest
                go 1.17

                require {import_path} {version}
                """
            ),
        }
    )
    rule_runner.write_files(files)
    rule_runner.set_options(
        [
            f"--golang-subprocess-env-vars=GOPROXY=file://{rule_runner.build_root}/go-mod-proxy",
            "--golang-subprocess-env-vars=GOSUMDB=off",
        ],
        env_inherit={"PATH"},
    )

    prefix = f"gopath/pkg/mod/{import_path}@{version}"

    def get_build_request(pkg_import_path: str) -> BuildGoPackageRequest:
        return rule_runner.request(
            BuildGoPackageRequest,
            [
                BuildGoPackageRequestForThirdPartyPackageRequest(
                    import_path=pkg_import_path,
                    go_mod_address=Address("", target_name="mod"),
                    build_opts=GoBuildOptions(),
                )
            ],
        )

    def digest_files(request: BuildGoPackageRequest) -> set[str]:
        return set(rule_runner.request(Snapshot, [request.digest]).files)

    pure_request = get_build_request(f"{import_path}/pure")
    assert digest_files(pure_request) == {
        f"{prefix}/pure/pure.go",
        f"{prefix}/pure/helpers[gen].go",
    }

    embedder_request = get_build_request(f"{import_path}/embedder")
    assert digest_files(embedder_request) == {
        f"{prefix}/embedder/embedder.go",
        f"{prefix}/embedder/data/msg.txt",
    }

    # Native-code packages keep the whole module.
    native_files = digest_files(get_build_request(f"{import_path}/native"))
    assert f"{prefix}/other/other.go" in native_files

    # The sliced packages still compile.
    assert_built(rule_runner, pure_request, expected_import_paths=[f"{import_path}/pure"])
    assert_built(rule_runner, embedder_request, expected_import_paths=[f"{import_path}/embedder"])


def test_build_target_with_dependencies(rule_runner: RuleRunner) -> None:
    """Check that we properly include (transitive) dependencies."""
    rule_runner.write_files(
        {
            "greeter/quoter/lib.go": dedent(
                """\
                package quoter

                import "fmt"

                func Quote(s string) string {
                    return fmt.Sprintf(">> %s <<", s)
                }
                """
            ),
            "greeter/quoter/BUILD": "go_package()",
            "greeter/lib.go": dedent(
                """\
                package greeter

                import (
                    "fmt"
                    "example.com/project/greeter/quoter"
                    "golang.org/x/xerrors"
                )

                func QuotedHello() {
                    xerrors.New("some error")
                    fmt.Println(quoter.Quote("Hello world!"))
                }
                """
            ),
            "greeter/BUILD": "go_package()",
            "main.go": dedent(
                """\
                package main

                import "example.com/project/greeter"

                func main() {
                    greeter.QuotedHello()
                }
                """
            ),
            "go.mod": dedent(
                """\
                module example.com/project
                go 1.17
                require golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543
                """
            ),
            "go.sum": dedent(
                """\
                golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543 h1:E7g+9GITq07hpfrRu66IVDexMakfv52eLZ2CXBWiKr4=
                golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543/go.mod h1:I/5z698sn9Ka8TeJc9MKroUUfqBBauWjQqLJ2OPfmY0=
                """
            ),
            "BUILD": "go_mod(name='mod')\ngo_package(name='pkg')",
        }
    )

    xerrors_internal_import_path = "golang.org/x/xerrors/internal"
    assert_pkg_target_built(
        rule_runner,
        Address("", target_name="mod", generated_name=xerrors_internal_import_path),
        expected_import_path=xerrors_internal_import_path,
        expected_dir_path="gopath/pkg/mod/golang.org/x/xerrors@v0.0.0-20191204190536-9bdfabe68543/internal",
        expected_go_file_names=["internal.go"],
        expected_direct_dependency_import_paths=[],
        expected_transitive_dependency_import_paths=[],
    )

    xerrors_import_path = "golang.org/x/xerrors"
    assert_pkg_target_built(
        rule_runner,
        Address("", target_name="mod", generated_name=xerrors_import_path),
        expected_import_path=xerrors_import_path,
        expected_dir_path="gopath/pkg/mod/golang.org/x/xerrors@v0.0.0-20191204190536-9bdfabe68543",
        expected_go_file_names=[
            "adaptor.go",
            "doc.go",
            "errors.go",
            "fmt.go",
            "format.go",
            "frame.go",
            "wrap.go",
        ],
        expected_direct_dependency_import_paths=[
            "bytes",
            "fmt",
            xerrors_internal_import_path,
            "io",
            "reflect",
            "runtime",
            "strconv",
            "strings",
            "unicode",
            "unicode/utf8",
        ],
        expected_transitive_dependency_import_paths=[],
    )

    quoter_import_path = "example.com/project/greeter/quoter"
    assert_pkg_target_built(
        rule_runner,
        Address("greeter/quoter"),
        expected_import_path=quoter_import_path,
        expected_dir_path="greeter/quoter",
        expected_go_file_names=["lib.go"],
        expected_direct_dependency_import_paths=["fmt"],
        expected_transitive_dependency_import_paths=[],
    )

    greeter_import_path = "example.com/project/greeter"
    assert_pkg_target_built(
        rule_runner,
        Address("greeter"),
        expected_import_path=greeter_import_path,
        expected_dir_path="greeter",
        expected_go_file_names=["lib.go"],
        expected_direct_dependency_import_paths=["fmt", xerrors_import_path, quoter_import_path],
        expected_transitive_dependency_import_paths=[xerrors_internal_import_path],
    )

    assert_pkg_target_built(
        rule_runner,
        Address("", target_name="pkg"),
        expected_import_path="example.com/project",
        expected_dir_path="",
        expected_go_file_names=["main.go"],
        expected_direct_dependency_import_paths=[greeter_import_path],
        expected_transitive_dependency_import_paths=[
            quoter_import_path,
            xerrors_import_path,
            xerrors_internal_import_path,
        ],
    )


def test_build_invalid_target(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "go.mod": dedent(
                """\
                module example.com/greeter
                go 1.17
                """
            ),
            "BUILD": "go_mod(name='mod')",
            "direct/f.go": "invalid!!!",
            "direct/BUILD": "go_package()",
            "dep/f.go": "invalid!!!",
            "dep/BUILD": "go_package()",
            "uses_dep/f.go": dedent(
                """\
                package uses_dep

                import "example.com/greeter/dep"

                func Hello() {
                    dep.Foo("Hello world!")
                }
                """
            ),
            "uses_dep/BUILD": "go_package()",
        }
    )

    direct_build_request = rule_runner.request(
        FallibleBuildGoPackageRequest,
        [BuildGoPackageTargetRequest(Address("direct"), build_opts=GoBuildOptions())],
    )
    assert direct_build_request.request is None
    assert direct_build_request.exit_code == 1
    assert "direct/f.go:1:1: expected 'package', found invalid\n" in (
        direct_build_request.stderr or ""
    )

    dep_build_request = rule_runner.request(
        FallibleBuildGoPackageRequest,
        [BuildGoPackageTargetRequest(Address("uses_dep"), build_opts=GoBuildOptions())],
    )
    assert dep_build_request.request is None
    assert dep_build_request.exit_code == 1
    assert "dep/f.go:1:1: expected 'package', found invalid\n" in (dep_build_request.stderr or "")


def test_build_codegen_target(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "go.mod": dedent(
                """\
                module example.com/greeter
                go 1.17
                require github.com/google/uuid v1.3.0
                """
            ),
            "go.sum": dedent(
                """\
                github.com/google/uuid v1.3.0 h1:t6JiXgmwXMjEs8VusXIJk2BXHsn+wx8BZdTaoZ5fu7I=
                github.com/google/uuid v1.3.0/go.mod h1:TIyPZe4MgqvfeYDBFedMoGGpEw/LqOeaOT+nhxU+yHo=
                """
            ),
            "generate_from_me.txt": "",
            "greeter.go": dedent(
                """\
                package greeter

                import "fmt"
                import "codegen.com/gen"

                func Hello() {
                    fmt.Println(gen.Quote("Hello world!"))
                }
                """
            ),
            "BUILD": dedent(
                """\
                go_mod(name='mod')
                go_package(name='pkg', dependencies=[":gen"])
                files(
                    name='gen',
                    sources=['generate_from_me.txt'],
                    dependencies=[':mod#github.com/google/uuid'],
                )
                """
            ),
        }
    )

    # Running directly on a codegen target should work.
    assert_pkg_target_built(
        rule_runner,
        Address("", target_name="gen", relative_file_path="generate_from_me.txt"),
        expected_import_path="codegen.com/gen",
        expected_dir_path="codegen",
        expected_go_file_names=["f.go"],
        expected_direct_dependency_import_paths=["fmt", "github.com/google/uuid"],
        expected_transitive_dependency_import_paths=[],
    )

    # Direct dependencies on codegen targets must be propagated.
    #
    # Note that the `go_package` depends on the `files` generator target. This should work, even
    # though `files` itself cannot generate, because it's an alias for all generated `file` targets.
    assert_pkg_target_built(
        rule_runner,
        Address("", target_name="pkg"),
        expected_import_path="example.com/greeter",
        expected_dir_path="",
        expected_go_file_names=["greeter.go"],
        expected_direct_dependency_import_paths=["codegen.com/gen", "fmt"],
        expected_transitive_dependency_import_paths=["github.com/google/uuid"],
    )


def test_xtest_deps(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "go.mod": "module example.pantsbuild.org",
            "BUILD": "go_mod(name='mod')\n",
            "pkg/BUILD": "go_package()\n",
            "pkg/example.go": dedent(
                """\
            package pkg

            const ExampleValue = 2137
            """
            ),
            "pkg/example_test.go": dedent(
                """\
            package pkg_test

            import (
                "example.pantsbuild.org/pkg"
                "example.pantsbuild.org/pkg/testutils"
                "testing"
            )

            func TestValue(t *testing.T) {
                t.Run("Test", func(t *testing.T) {
                    if pkg.ExampleValue != testutils.ExampleValueFromTestutils {
                        t.Error("Not equal")
                    }
                })
            }
            """
            ),
            "pkg/testutils/BUILD": "go_package()\n",
            "pkg/testutils/testutils.go": dedent(
                """\
            package testutils

            import "example.pantsbuild.org/pkg"

            const ExampleValueFromTestutils = pkg.ExampleValue
            """
            ),
        }
    )
    assert_pkg_target_built(
        rule_runner,
        Address("pkg"),
        expected_dir_path="pkg",
        expected_import_path="example.pantsbuild.org/pkg",
        expected_go_file_names=["example.go"],
        expected_direct_dependency_import_paths=[],
        expected_transitive_dependency_import_paths=[],
    )


@pytest.mark.no_error_if_skipped
def test_stdlib_embed_config(rule_runner: RuleRunner) -> None:
    # This test exercises embed-config resolution on the from-source stdlib path. With
    # pre-built stdlib archives enabled (the default), stdlib build requests are "slim" and
    # carry no embed config (the harvested archives already incorporate embedded files).
    rule_runner.set_options(["--no-golang-use-prebuilt-stdlib-archives"], env_inherit={"PATH"})
    stdlib_packages = rule_runner.request(
        GoStdLibPackages, [GoStdLibPackagesRequest(with_race_detector=False, cgo_enabled=False)]
    )

    pkg_info: GoStdLibPackage | None = None
    for import_path in ("crypto/internal/nistec", "internal/trace/traceviewer/http"):
        pkg_info = stdlib_packages.get(import_path)
        if pkg_info:
            break

    if not pkg_info:
        pytest.skip(
            "Skipping test since no known stdlib import paths using embed are available for the test."
        )

    assert "embed" in pkg_info.imports
    assert pkg_info.embed_patterns
    assert pkg_info.embed_files

    build_request = rule_runner.request(
        BuildGoPackageRequest,
        [
            BuildGoPackageRequestForStdlibRequest(
                import_path=pkg_info.import_path, build_opts=GoBuildOptions(cgo_enabled=False)
            )
        ],
    )

    embed_config = build_request.embed_config
    assert embed_config is not None
    assert embed_config.patterns
    assert embed_config.files


def test_stdlib_prebuilt_archives_used(rule_runner: RuleRunner) -> None:
    """With pre-built stdlib archives enabled (the default), stdlib dependency requests are
    "slim" (no sources, no dependency recursion) and the built output maps stdlib packages to
    pre-built archives instead of from-source `__pkgs__/...` archives."""
    rule_runner.write_files(
        {
            "go.mod": dedent(
                """\
                module example.com/stdlib-user
                go 1.17
                """
            ),
            "hasher.go": dedent(
                """\
                package hasher

                import (
                    "crypto/sha256"
                    "fmt"
                )

                func Hash(b []byte) string {
                    return fmt.Sprintf("%x", sha256.Sum256(b))
                }
                """
            ),
            "BUILD": "go_mod(name='mod')\ngo_package(name='pkg')",
        }
    )
    build_request = rule_runner.request(
        BuildGoPackageRequest,
        [BuildGoPackageTargetRequest(Address("", target_name="pkg"), build_opts=GoBuildOptions())],
    )

    # Structural: every stdlib dependency request in the DAG is slim, so no path exists by
    # which a stdlib package could be compiled from source.
    stdlib_dep_requests = [dep for dep in build_request.direct_dependencies if dep.is_stdlib]
    assert sorted(dep.import_path for dep in stdlib_dep_requests) == ["crypto/sha256", "fmt"]
    for dep in stdlib_dep_requests:
        assert dep.go_files == ()
        assert dep.s_files == ()
        assert dep.direct_dependencies == ()

    # Output: stdlib archives come from the harvest layout, and the full transitive stdlib
    # closure (e.g. `runtime`) is available for the link step even though no build request
    # was ever constructed for it.
    built_package = rule_runner.request(BuiltGoPackage, [build_request])
    archive_paths = {ip: path for ip, (path, _) in built_package.transitive_pkg_archives.items()}
    assert archive_paths["crypto/sha256"] == "__go_stdlib__/crypto/sha256.a"
    assert archive_paths["fmt"] == "__go_stdlib__/fmt.a"
    assert archive_paths["runtime"] == "__go_stdlib__/runtime.a"
    assert archive_paths["example.com/stdlib-user"] == os.path.join(
        "__pkgs__", path_safe("example.com/stdlib-user"), "__pkg__.a"
    )


def test_build_with_race_detector_falls_back(rule_runner: RuleRunner) -> None:
    """Build options that change stdlib archive content (e.g. the race detector) must fall
    back to full from-source stdlib build requests."""
    build_request = rule_runner.request(
        BuildGoPackageRequest,
        [
            BuildGoPackageRequestForStdlibRequest(
                # NB: cgo must stay enabled: `-race requires cgo`.
                "fmt",
                build_opts=GoBuildOptions(cgo_enabled=True, with_race_detector=True),
            )
        ],
    )
    assert build_request.is_stdlib
    assert build_request.go_files, "expected a non-slim request with sources present"
    assert build_request.direct_dependencies, (
        "expected a non-slim request with dependency recursion"
    )
