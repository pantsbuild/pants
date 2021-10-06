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
    GoExternalModulePathField,
    GoExternalModuleVersionField,
    GoExternalPackageTarget,
    GoImportPathField,
    GoInternalPackageSourcesField,
    GoInternalPackageSubpathField,
    GoInternalPackageTarget,
    GoModTarget,
)
from pants.backend.go.util_rules import external_pkg, go_mod, go_pkg, sdk
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
)
from pants.testutil.rule_runner import RuleRunner, engine_error
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *go_mod.rules(),
            *go_pkg.rules(),
            *external_pkg.rules(),
            *sdk.rules(),
            *target_type_rules.rules(),
            QueryRule(Addresses, [DependenciesRequest]),
            QueryRule(GoBinaryMainPackage, [GoBinaryMainPackageRequest]),
            QueryRule(InjectedDependencies, [InjectGoBinaryMainDependencyRequest]),
        ],
        target_types=[GoModTarget, GoBinaryTarget, GenericTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_go_package_dependency_injection(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "dir1/go.mod": "module foo",
            "dir1/BUILD": "go_mod()",
            "dir1/pkg/foo.go": "package pkg",
            "dir2/bar/go.mod": "module bar",
            "dir2/bar/src.go": "package bar",
            "dir2/bar/BUILD": "go_mod()",
        }
    )

    def assert_go_mod(pkg: Address, go_mod: Address) -> None:
        tgt = rule_runner.get_target(pkg)
        deps = rule_runner.request(Addresses, [DependenciesRequest(tgt[Dependencies])])
        assert set(deps) == {go_mod}

    assert_go_mod(Address("dir1", generated_name="./pkg"), Address("dir1"))
    assert_go_mod(Address("dir2/bar", generated_name="./"), Address("dir2/bar"))


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
                "foo/pkg/foo.go": dedent(
                    """\
                    package pkg
                    import "github.com/google/go-cmp/cmp"
                    func grok(left, right string) bool {
                        return cmp.Equal(left, right)
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
            }
        )
    )
    tgt1 = rule_runner.get_target(Address("foo", generated_name="./cmd"))
    inferred_deps1 = rule_runner.request(
        InferredDependencies,
        [InferGoPackageDependenciesRequest(tgt1[GoInternalPackageSourcesField])],
    )
    assert inferred_deps1.dependencies == FrozenOrderedSet([Address("foo", generated_name="./pkg")])

    tgt2 = rule_runner.get_target(Address("foo", generated_name="./pkg"))
    inferred_deps2 = rule_runner.request(
        InferredDependencies,
        [InferGoPackageDependenciesRequest(tgt2[GoInternalPackageSourcesField])],
    )
    assert inferred_deps2.dependencies == FrozenOrderedSet(
        [Address("foo", generated_name="github.com/google/go-cmp/cmp")]
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
            "src/go/another_dir/subdir/another_dir/f.go": "",
        }
    )
    generator = rule_runner.get_target(Address("src/go"))
    generated = rule_runner.request(GeneratedTargets, [GenerateTargetsFromGoModRequest(generator)])

    def gen_internal_tgt(rel_dir: str) -> GoInternalPackageTarget:
        return GoInternalPackageTarget(
            {
                GoImportPathField.alias: (
                    os.path.join("example.com/src/go", rel_dir) if rel_dir else "example.com/src/go"
                ),
                GoInternalPackageSubpathField.alias: rel_dir,
                GoInternalPackageSourcesField.alias: tuple(
                    os.path.join(rel_dir, glob) for glob in GoInternalPackageSourcesField.default
                ),
            },
            Address("src/go", generated_name=f"./{rel_dir}"),
        )

    def gen_external_tgt(mod_path: str, version: str, import_path: str) -> GoExternalPackageTarget:
        return GoExternalPackageTarget(
            {
                GoImportPathField.alias: import_path,
                GoExternalModulePathField.alias: mod_path,
                GoExternalModuleVersionField.alias: version,
            },
            Address("src/go", generated_name=import_path),
        )

    expected = GeneratedTargets(
        generator,
        {
            gen_internal_tgt(""),
            gen_internal_tgt("subdir"),
            gen_internal_tgt("another_dir/subdir/another_dir"),
            gen_external_tgt("github.com/google/uuid", "v1.2.0", "github.com/google/uuid"),
            gen_external_tgt("github.com/google/go-cmp", "v0.4.0", "github.com/google/go-cmp/cmp"),
            gen_external_tgt(
                "github.com/google/go-cmp", "v0.4.0", "github.com/google/go-cmp/cmp/cmpopts"
            ),
            gen_external_tgt(
                "github.com/google/go-cmp", "v0.4.0", "github.com/google/go-cmp/cmp/internal/diff"
            ),
            gen_external_tgt(
                "github.com/google/go-cmp", "v0.4.0", "github.com/google/go-cmp/cmp/internal/flags"
            ),
            gen_external_tgt(
                "github.com/google/go-cmp",
                "v0.4.0",
                "github.com/google/go-cmp/cmp/internal/function",
            ),
            gen_external_tgt(
                "github.com/google/go-cmp",
                "v0.4.0",
                "github.com/google/go-cmp/cmp/internal/testprotos",
            ),
            gen_external_tgt(
                "github.com/google/go-cmp",
                "v0.4.0",
                "github.com/google/go-cmp/cmp/internal/teststructs",
            ),
            gen_external_tgt(
                "github.com/google/go-cmp", "v0.4.0", "github.com/google/go-cmp/cmp/internal/value"
            ),
            gen_external_tgt(
                "golang.org/x/xerrors", "v0.0.0-20191204190536-9bdfabe68543", "golang.org/x/xerrors"
            ),
            gen_external_tgt(
                "golang.org/x/xerrors",
                "v0.0.0-20191204190536-9bdfabe68543",
                "golang.org/x/xerrors/internal",
            ),
        },
    )
    assert list(generated.keys()) == list(expected.keys())
    for addr, tgt in generated.items():
        assert tgt == expected[addr]


# -----------------------------------------------------------------------------------------------
# The `main` field for `go_binary`
# -----------------------------------------------------------------------------------------------


@pytest.mark.xfail
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
