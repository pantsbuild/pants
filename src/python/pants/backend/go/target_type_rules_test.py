# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.target_type_rules import (
    GenerateTargetsFromGoModRequest,
    InferGoPackageDependenciesRequest,
    InjectGoBinaryMainDependencyRequest,
)
from pants.backend.go.target_types import (
    GoBinaryMainPackage,
    GoBinaryMainPackageField,
    GoBinaryMainPackageRequest,
    GoBinaryTarget,
    GoFirstPartyPackageSourcesField,
    GoFirstPartyPackageSubpathField,
    GoFirstPartyPackageTarget,
    GoImportPathField,
    GoModTarget,
    GoThirdPartyPackageTarget,
)
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    first_party_pkg,
    go_mod,
    link,
    sdk,
    third_party_pkg,
)
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
    InvalidTargetException,
)
from pants.testutil.rule_runner import RuleRunner, engine_error
from pants.util.ordered_set import FrozenOrderedSet

# -----------------------------------------------------------------------------------------------
# Dependency inference
# -----------------------------------------------------------------------------------------------


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *go_mod.rules(),
            *first_party_pkg.rules(),
            *third_party_pkg.rules(),
            *sdk.rules(),
            *target_type_rules.rules(),
            *build_pkg.rules(),
            *link.rules(),
            *assembly.rules(),
            QueryRule(Addresses, [DependenciesRequest]),
            QueryRule(GoBinaryMainPackage, [GoBinaryMainPackageRequest]),
            QueryRule(InjectedDependencies, [InjectGoBinaryMainDependencyRequest]),
        ],
        target_types=[GoModTarget, GoBinaryTarget, GenericTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_go_package_dependency_inference(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod()",
            "foo/go.mod": dedent(
                """\
                    module go.example.com/foo
                    go 1.17

                    require github.com/google/uuid v1.3.0
                    """
            ),
            "foo/go.sum": dedent(
                """\
                github.com/google/uuid v1.3.0 h1:t6JiXgmwXMjEs8VusXIJk2BXHsn+wx8BZdTaoZ5fu7I=
                github.com/google/uuid v1.3.0/go.mod h1:TIyPZe4MgqvfeYDBFedMoGGpEw/LqOeaOT+nhxU+yHo=
                """
            ),
            "foo/pkg/foo.go": dedent(
                """\
                    package pkg
                    import "github.com/google/uuid"
                    func Grok() string {
                        return uuid.Foo()
                    }
                    """
            ),
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
            "foo/bad/f.go": "invalid!!!",
        }
    )
    tgt1 = rule_runner.get_target(Address("foo", generated_name="./cmd"))
    inferred_deps1 = rule_runner.request(
        InferredDependencies,
        [InferGoPackageDependenciesRequest(tgt1[GoFirstPartyPackageSourcesField])],
    )
    assert inferred_deps1.dependencies == FrozenOrderedSet([Address("foo", generated_name="./pkg")])

    tgt2 = rule_runner.get_target(Address("foo", generated_name="./pkg"))
    inferred_deps2 = rule_runner.request(
        InferredDependencies,
        [InferGoPackageDependenciesRequest(tgt2[GoFirstPartyPackageSourcesField])],
    )
    assert inferred_deps2.dependencies == FrozenOrderedSet(
        [Address("foo", generated_name="github.com/google/uuid")]
    )

    # Compilation failures should not blow up Pants.
    bad_tgt = rule_runner.get_target(Address("foo", generated_name="./bad"))
    assert not rule_runner.request(
        InferredDependencies,
        [InferGoPackageDependenciesRequest(bad_tgt[GoFirstPartyPackageSourcesField])],
    )


# -----------------------------------------------------------------------------------------------
# Generate package targets from `go_mod`
# -----------------------------------------------------------------------------------------------


def test_generate_package_targets(rule_runner: RuleRunner) -> None:
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
                    golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543 // indirect
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
            "src/go/hello.go": "",
            "src/go/subdir/f.go": "",
            "src/go/subdir/f2.go": "",
            "src/go/another_dir/subdir/f.go": "",
        }
    )
    generator = rule_runner.get_target(Address("src/go"))
    generated = rule_runner.request(GeneratedTargets, [GenerateTargetsFromGoModRequest(generator)])

    def gen_first_party_tgt(rel_dir: str, sources: list[str]) -> GoFirstPartyPackageTarget:
        return GoFirstPartyPackageTarget(
            {
                GoImportPathField.alias: (
                    os.path.join("example.com/src/go", rel_dir) if rel_dir else "example.com/src/go"
                ),
                GoFirstPartyPackageSubpathField.alias: rel_dir,
                GoFirstPartyPackageSourcesField.alias: tuple(sources),
            },
            Address("src/go", generated_name=f"./{rel_dir}"),
            residence_dir=os.path.join("src/go", rel_dir).rstrip("/"),
        )

    def gen_third_party_tgt(import_path: str) -> GoThirdPartyPackageTarget:
        return GoThirdPartyPackageTarget(
            {GoImportPathField.alias: import_path},
            Address("src/go", generated_name=import_path),
        )

    expected = GeneratedTargets(
        generator,
        {
            gen_first_party_tgt("", ["hello.go"]),
            gen_first_party_tgt("subdir", ["subdir/f.go", "subdir/f2.go"]),
            gen_first_party_tgt("another_dir/subdir", ["another_dir/subdir/f.go"]),
            *(
                gen_third_party_tgt(pkg)
                for pkg in (
                    "github.com/google/uuid",
                    "github.com/google/go-cmp/cmp",
                    "github.com/google/go-cmp/cmp/cmpopts",
                    "github.com/google/go-cmp/cmp/internal/diff",
                    "github.com/google/go-cmp/cmp/internal/flags",
                    "github.com/google/go-cmp/cmp/internal/function",
                    "github.com/google/go-cmp/cmp/internal/testprotos",
                    "github.com/google/go-cmp/cmp/internal/teststructs",
                    "github.com/google/go-cmp/cmp/internal/value",
                    "golang.org/x/xerrors",
                    "golang.org/x/xerrors/internal",
                )
            ),
        },
    )
    assert list(generated.keys()) == list(expected.keys())
    for addr, tgt in generated.items():
        assert tgt == expected[addr]


def test_package_targets_cannot_be_manually_created() -> None:
    with pytest.raises(InvalidTargetException):
        GoFirstPartyPackageTarget(
            {GoImportPathField.alias: "foo", GoFirstPartyPackageSubpathField.alias: "foo"},
            Address("foo"),
        )
    with pytest.raises(InvalidTargetException):
        GoThirdPartyPackageTarget(
            {GoImportPathField.alias: "foo"},
            Address("foo"),
        )


# -----------------------------------------------------------------------------------------------
# The `main` field for `go_binary`
# -----------------------------------------------------------------------------------------------


def test_determine_main_pkg_for_go_binary(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "go.mod": dedent(
                """\
                module example.com/foo
                go 1.17
                """
            ),
            "BUILD": "go_mod(name='mod')",
            "explicit/f.go": "",
            "explicit/BUILD": "go_binary(main='//:mod#./explicit')",
            "inferred/f.go": "",
            "inferred/BUILD": "go_binary()",
            "ambiguous/f.go": "",
            "ambiguous/go.mod": dedent(
                """\
                module example.com/ambiguous
                go 1.17
                """
            ),
            "ambiguous/BUILD": "go_binary()",
            # Note there are no `.go` files in this dir, so no package targets will be created.
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

    assert get_main(Address("explicit")) == Address(
        "", target_name="mod", generated_name="./explicit"
    )
    assert get_main(Address("inferred")) == Address(
        "", target_name="mod", generated_name="./inferred"
    )

    with engine_error(ResolveError, contains="none were found"):
        get_main(Address("missing"))
    with engine_error(ResolveError, contains="There are multiple `go_first_party_package` targets"):
        get_main(Address("ambiguous"))
    with engine_error(
        InvalidFieldException, contains="must point to a `go_first_party_package` target"
    ):
        get_main(Address("explicit_wrong_type"))
