# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.target_type_rules import (
    GenerateGoExternalPackageTargetsRequest,
    InferGoPackageDependenciesRequest,
    InjectGoBinaryMainDependencyRequest,
)
from pants.backend.go.target_types import (
    GoBinaryMainPackage,
    GoBinaryMainPackageField,
    GoBinaryMainPackageRequest,
    GoBinaryTarget,
    GoExternalModulePathField,
    GoExternalModuleVersionField,
    GoExternalPackageImportPathField,
    GoExternalPackageTarget,
    GoImportPathsDependenciesField,
    GoModSourcesField,
    GoModTarget,
    GoPackage,
    GoPackageSources,
)
from pants.backend.go.util_rules import external_module, go_mod, go_pkg, sdk
from pants.base.exceptions import ResolveError
from pants.build_graph.address import Address
from pants.core.target_types import GenericTarget
from pants.engine.addresses import Addresses
from pants.engine.rules import QueryRule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    GeneratedTargets,
    InferredDependencies,
    InjectedDependencies,
    InvalidFieldException,
    Target,
    Targets,
)
from pants.testutil.rule_runner import RuleRunner, engine_error
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *go_mod.rules(),
            *go_pkg.rules(),
            *external_module.rules(),
            *sdk.rules(),
            *target_type_rules.rules(),
            QueryRule(Addresses, [DependenciesRequest]),
            QueryRule(GoBinaryMainPackage, [GoBinaryMainPackageRequest]),
            QueryRule(InjectedDependencies, [InjectGoBinaryMainDependencyRequest]),
        ],
        target_types=[
            GoPackage,
            GoModTarget,
            GoExternalPackageTarget,
            GoBinaryTarget,
            GenericTarget,
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def assert_go_mod_address(rule_runner: RuleRunner, target: Target, expected_address: Address):
    addresses = rule_runner.request(Addresses, [DependenciesRequest(target[Dependencies])])
    targets = rule_runner.request(Targets, [addresses])
    go_mod_targets = [tgt for tgt in targets if tgt.has_field(GoModSourcesField)]
    assert len(go_mod_targets) == 1
    assert go_mod_targets[0].address == expected_address


def test_go_package_dependency_injection(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod()\n",
            "foo/go.mod": "module foo\n",
            "foo/go.sum": "",
            "foo/pkg/BUILD": "go_package()\n",
            "foo/pkg/foo.go": "package pkg\n",
            "foo/bar/BUILD": "go_mod()\ngo_package(name='pkg')\n",
            "foo/bar/go.mod": "module bar\n",
            "foo/bar/src.go": "package bar\n",
        }
    )

    target = rule_runner.get_target(Address("foo/pkg", target_name="pkg"))
    assert_go_mod_address(rule_runner, target, Address("foo"))

    target = rule_runner.get_target(Address("foo/bar", target_name="pkg"))
    assert_go_mod_address(rule_runner, target, Address("foo/bar"))


def test_go_package_dependency_inference(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        (
            {
                "foo/BUILD": "go_mod()",
                "foo/go.mod": dedent(
                    """\
                    module go.example.com/foo
                    go 1.17

                    require github.com/google/go-cmp v0.4.0
                    """
                ),
                "foo/go.sum": dedent(
                    """\
                    github.com/google/go-cmp v0.4.0 h1:xsAVV57WRhGj6kEIi8ReJzQlHHqcBYCElAvkovg3B/4=
                    github.com/google/go-cmp v0.4.0/go.mod h1:v8dTdLbMG2kIc/vJvl+f65V22dbkXbowE6jgT/gNBxE=
                    golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543 h1:E7g+9GITq07hpfrRu66IVDexMakfv52eLZ2CXBWiKr4=
                    golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543/go.mod h1:I/5z698sn9Ka8TeJc9MKroUUfqBBauWjQqLJ2OPfmY0=
                    """
                ),
                "foo/pkg/BUILD": "go_package()\n",
                "foo/pkg/foo.go": dedent(
                    """\
                    package pkg
                    import "github.com/google/go-cmp/cmp"
                    func grok(left, right string) bool {
                        return cmp.Equal(left, right)
                    }
                    """
                ),
                "foo/cmd/BUILD": "go_package()\n",
                "foo/cmd/main.go": dedent(
                    """\
                    package main
                    import (
                        "fmt"
                        "go.example.com/foo/pkg"
                    )
                    func main() {
                        fmt.Printf("%s\n", pkg.Grok())
                    }"""
                ),
            }
        )
    )
    target1 = rule_runner.get_target(Address("foo/cmd"))
    inferred_deps_1 = rule_runner.request(
        InferredDependencies, [InferGoPackageDependenciesRequest(target1[GoPackageSources])]
    )
    assert inferred_deps_1.dependencies == FrozenOrderedSet([Address("foo/pkg")])

    target2 = rule_runner.get_target(Address("foo/pkg"))
    inferred_deps_2 = rule_runner.request(
        InferredDependencies, [InferGoPackageDependenciesRequest(target2[GoPackageSources])]
    )
    assert inferred_deps_2.dependencies == FrozenOrderedSet(
        [Address("foo", generated_name="github.com/google/go-cmp/cmp")]
    )


# -----------------------------------------------------------------------------------------------
# Generate `_go_external_package` targets
# -----------------------------------------------------------------------------------------------


def test_generate_go_external_package_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/go/BUILD": "go_mod()\n",
            "src/go/go.mod": dedent(
                """\
                module example.com/src/go
                go 1.17

                require (
                    github.com/google/go-cmp v0.4.0
                    github.com/google/uuid v1.2.0
                )
                """
            ),
            "src/go/go.sum": dedent(
                """\
                github.com/google/go-cmp v0.4.0 h1:xsAVV57WRhGj6kEIi8ReJzQlHHqcBYCElAvkovg3B/4=
                github.com/google/go-cmp v0.4.0/go.mod h1:v8dTdLbMG2kIc/vJvl+f65V22dbkXbowE6jgT/gNBxE=
                github.com/google/uuid v1.2.0 h1:qJYtXnJRWmpe7m/3XlyhrsLrEURqHRM2kxzoxXqyUDs=
                github.com/google/uuid v1.2.0/go.mod h1:TIyPZe4MgqvfeYDBFedMoGGpEw/LqOeaOT+nhxU+yHo=
                golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543 h1:E7g+9GITq07hpfrRu66IVDexMakfv52eLZ2CXBWiKr4=
                golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543/go.mod h1:I/5z698sn9Ka8TeJc9MKroUUfqBBauWjQqLJ2OPfmY0=
                """
            ),
        }
    )
    generator = rule_runner.get_target(Address("src/go"))
    generated = rule_runner.request(
        GeneratedTargets, [GenerateGoExternalPackageTargetsRequest(generator)]
    )

    def gen_tgt(
        mod_path: str, version: str, import_path: str, import_path_deps: list[str]
    ) -> GoExternalPackageTarget:
        return GoExternalPackageTarget(
            {
                GoExternalModulePathField.alias: mod_path,
                GoExternalModuleVersionField.alias: version,
                GoExternalPackageImportPathField.alias: import_path,
                GoImportPathsDependenciesField.alias: import_path_deps,
            },
            Address("src/go", generated_name=import_path),
        )

    expected = GeneratedTargets(
        generator,
        {
            gen_tgt(
                "github.com/google/uuid",
                "v1.2.0",
                "github.com/google/uuid",
                [
                    "bytes",
                    "crypto/md5",
                    "crypto/rand",
                    "crypto/sha1",
                    "database/sql/driver",
                    "encoding/binary",
                    "encoding/hex",
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
            ),
            gen_tgt(
                "github.com/google/go-cmp",
                "v0.4.0",
                "github.com/google/go-cmp/cmp",
                [
                    "bytes",
                    "fmt",
                    "github.com/google/go-cmp/cmp/internal/diff",
                    "github.com/google/go-cmp/cmp/internal/flags",
                    "github.com/google/go-cmp/cmp/internal/function",
                    "github.com/google/go-cmp/cmp/internal/value",
                    "math/rand",
                    "reflect",
                    "regexp",
                    "strconv",
                    "strings",
                    "time",
                    "unicode",
                    "unicode/utf8",
                    "unsafe",
                ],
            ),
            gen_tgt(
                "github.com/google/go-cmp",
                "v0.4.0",
                "github.com/google/go-cmp/cmp/cmpopts",
                [
                    "fmt",
                    "github.com/google/go-cmp/cmp",
                    "github.com/google/go-cmp/cmp/internal/function",
                    "golang.org/x/xerrors",
                    "math",
                    "reflect",
                    "sort",
                    "strings",
                    "time",
                    "unicode",
                    "unicode/utf8",
                ],
            ),
            gen_tgt(
                "github.com/google/go-cmp",
                "v0.4.0",
                "github.com/google/go-cmp/cmp/internal/diff",
                [],
            ),
            gen_tgt(
                "github.com/google/go-cmp",
                "v0.4.0",
                "github.com/google/go-cmp/cmp/internal/flags",
                [],
            ),
            gen_tgt(
                "github.com/google/go-cmp",
                "v0.4.0",
                "github.com/google/go-cmp/cmp/internal/function",
                ["reflect", "regexp", "runtime", "strings"],
            ),
            gen_tgt(
                "github.com/google/go-cmp",
                "v0.4.0",
                "github.com/google/go-cmp/cmp/internal/testprotos",
                [],
            ),
            gen_tgt(
                "github.com/google/go-cmp",
                "v0.4.0",
                "github.com/google/go-cmp/cmp/internal/teststructs",
                ["github.com/google/go-cmp/cmp/internal/testprotos", "sync", "time"],
            ),
            gen_tgt(
                "github.com/google/go-cmp",
                "v0.4.0",
                "github.com/google/go-cmp/cmp/internal/value",
                ["fmt", "math", "reflect", "sort", "unsafe"],
            ),
            gen_tgt(
                "golang.org/x/xerrors",
                "v0.0.0-20191204190536-9bdfabe68543",
                "golang.org/x/xerrors",
                [
                    "bytes",
                    "fmt",
                    "golang.org/x/xerrors/internal",
                    "io",
                    "reflect",
                    "runtime",
                    "strconv",
                    "strings",
                    "unicode",
                    "unicode/utf8",
                ],
            ),
            gen_tgt(
                "golang.org/x/xerrors",
                "v0.0.0-20191204190536-9bdfabe68543",
                "golang.org/x/xerrors/internal",
                [],
            ),
        },
    )
    assert list(generated.keys()) == list(expected.keys())
    assert generated == expected


# -----------------------------------------------------------------------------------------------
# The `main` field for `go_binary`
# -----------------------------------------------------------------------------------------------


def test_determine_main_pkg_for_go_binary(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "explicit/BUILD": dedent(
                """\
                go_package(name='pkg', sources=[])
                go_binary(main=':pkg')
                """
            ),
            "inferred/BUILD": dedent(
                """\
                go_package(name='pkg', sources=[])
                go_binary()
                """
            ),
            "ambiguous/BUILD": dedent(
                """\
                go_package(name='pkg1', sources=[])
                go_package(name='pkg2', sources=[])
                go_binary()
                """
            ),
            "missing/BUILD": "go_binary()",
            "explicit_wrong_type/BUILD": dedent(
                """\
                target(name='dep')
                go_binary(main=':dep')
                """
            ),
        }
    )

    def get_main(addr: Address) -> Address:
        tgt = rule_runner.get_target(addr)
        main_addr = rule_runner.request(
            GoBinaryMainPackage, [GoBinaryMainPackageRequest(tgt[GoBinaryMainPackageField])]
        ).address
        injected_addresses = rule_runner.request(
            InjectedDependencies, [InjectGoBinaryMainDependencyRequest(tgt[Dependencies])]
        )
        assert [main_addr] == list(injected_addresses)
        return main_addr

    assert get_main(Address("explicit")) == Address("explicit", target_name="pkg")
    assert get_main(Address("inferred")) == Address("inferred", target_name="pkg")

    with engine_error(ResolveError, contains="none were found"):
        get_main(Address("missing"))
    with engine_error(ResolveError, contains="There are multiple `go_package` targets"):
        get_main(Address("ambiguous"))
    with engine_error(InvalidFieldException, contains="must point to a `go_package` target"):
        get_main(Address("explicit_wrong_type"))
