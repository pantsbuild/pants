# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.target_types import GoModTarget, GoPackageTarget
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
from pants.backend.go.util_rules.build_pkg import (
    BuildGoPackageRequest,
    BuiltGoPackage,
    FallibleBuildGoPackageRequest,
    FallibleBuiltGoPackage,
)
from pants.backend.go.util_rules.build_pkg_target import (
    BuildGoPackageTargetRequest,
    GoCodegenBuildRequest,
)
from pants.core.target_types import FilesGeneratorTarget, FileSourceField
from pants.engine.addresses import Address, Addresses
from pants.engine.fs import CreateDigest, Digest, FileContent, Snapshot
from pants.engine.rules import Get, QueryRule, rule
from pants.engine.target import Dependencies, DependenciesRequest
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.strutil import path_safe


# Set up a semi-complex codegen plugin. Note that we cyclically call into the
# `BuildGoPackageTargetRequest` rule to set up a dependency on a third-party package, as this
# is common for codegen plugins to need to do.
class GoCodegenBuildFilesRequest(GoCodegenBuildRequest):
    generate_from = FileSourceField


@rule
async def generate_from_file(request: GoCodegenBuildFilesRequest) -> BuildGoPackageRequest:
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
    digest = await Get(Digest, CreateDigest([FileContent("codegen/f.go", content.encode())]))

    deps = await Get(Addresses, DependenciesRequest(request.target[Dependencies]))
    assert len(deps) == 1
    assert deps[0].generated_name == "github.com/google/uuid"
    thirdparty_dep = await Get(FallibleBuildGoPackageRequest, BuildGoPackageTargetRequest(deps[0]))
    assert thirdparty_dep.request is not None

    return BuildGoPackageRequest(
        import_path="codegen.com/gen",
        digest=digest,
        dir_path="codegen",
        go_file_names=("f.go",),
        s_file_names=(),
        direct_dependencies=(thirdparty_dep.request,),
        minimum_go_version=None,
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
            QueryRule(BuiltGoPackage, [BuildGoPackageRequest]),
            QueryRule(FallibleBuiltGoPackage, [BuildGoPackageRequest]),
            QueryRule(BuildGoPackageRequest, [BuildGoPackageTargetRequest]),
            QueryRule(FallibleBuildGoPackageRequest, [BuildGoPackageTargetRequest]),
            UnionRule(GoCodegenBuildRequest, GoCodegenBuildFilesRequest),
        ],
        target_types=[GoModTarget, GoPackageTarget, FilesGeneratorTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def assert_built(
    rule_runner: RuleRunner, request: BuildGoPackageRequest, *, expected_import_paths: list[str]
) -> None:
    built_package = rule_runner.request(BuiltGoPackage, [request])
    result_files = rule_runner.request(Snapshot, [built_package.digest]).files
    expected = {
        import_path: os.path.join("__pkgs__", path_safe(import_path), "__pkg__.a")
        for import_path in expected_import_paths
    }
    assert dict(built_package.import_paths_to_pkg_a_files) == expected
    assert sorted(result_files) == sorted(expected.values())


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
    build_request = rule_runner.request(BuildGoPackageRequest, [BuildGoPackageTargetRequest(addr)])
    assert build_request.import_path == expected_import_path
    assert build_request.dir_path == expected_dir_path
    assert build_request.go_file_names == tuple(expected_go_file_names)
    assert not build_request.s_file_names
    assert [
        dep.import_path for dep in build_request.direct_dependencies
    ] == expected_direct_dependency_import_paths
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
        expected_direct_dependency_import_paths=[],
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
        expected_direct_dependency_import_paths=[],
        expected_transitive_dependency_import_paths=[],
    )


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
        expected_direct_dependency_import_paths=[xerrors_internal_import_path],
        expected_transitive_dependency_import_paths=[],
    )

    quoter_import_path = "example.com/project/greeter/quoter"
    assert_pkg_target_built(
        rule_runner,
        Address("greeter/quoter"),
        expected_import_path=quoter_import_path,
        expected_dir_path="greeter/quoter",
        expected_go_file_names=["lib.go"],
        expected_direct_dependency_import_paths=[],
        expected_transitive_dependency_import_paths=[],
    )

    greeter_import_path = "example.com/project/greeter"
    assert_pkg_target_built(
        rule_runner,
        Address("greeter"),
        expected_import_path=greeter_import_path,
        expected_dir_path="greeter",
        expected_go_file_names=["lib.go"],
        expected_direct_dependency_import_paths=[xerrors_import_path, quoter_import_path],
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
        FallibleBuildGoPackageRequest, [BuildGoPackageTargetRequest(Address("direct"))]
    )
    assert direct_build_request.request is None
    assert direct_build_request.exit_code == 1
    assert "direct/f.go:1:1: expected 'package', found invalid\n" in (
        direct_build_request.stderr or ""
    )

    dep_build_request = rule_runner.request(
        FallibleBuildGoPackageRequest, [BuildGoPackageTargetRequest(Address("uses_dep"))]
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
        expected_direct_dependency_import_paths=["github.com/google/uuid"],
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
        expected_direct_dependency_import_paths=["codegen.com/gen"],
        expected_transitive_dependency_import_paths=["github.com/google/uuid"],
    )
