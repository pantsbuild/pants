# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import textwrap

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.target_type_rules import (
    GenerateGoExternalPackageTargetsRequest,
    InferGoPackageDependenciesRequest,
)
from pants.backend.go.target_types import (
    GoExternalModulePathField,
    GoExternalModuleVersionField,
    GoExternalPackageImportPathField,
    GoExternalPackageTarget,
    GoModSourcesField,
    GoModTarget,
    GoPackage,
    GoPackageSources,
)
from pants.backend.go.util_rules import external_module, go_mod, go_pkg, sdk
from pants.build_graph.address import Address
from pants.core.util_rules import external_tool, source_files
from pants.engine.addresses import Addresses
from pants.engine.rules import QueryRule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    GeneratedTargets,
    InferredDependencies,
    Target,
    Targets,
)
from pants.testutil.rule_runner import RuleRunner
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *external_tool.rules(),
            *source_files.rules(),
            *go_mod.rules(),
            *go_pkg.rules(),
            *external_module.rules(),
            *sdk.rules(),
            *target_type_rules.rules(),
            QueryRule(Addresses, [DependenciesRequest]),
            QueryRule(Targets, [Addresses]),
            QueryRule(InferredDependencies, [InferGoPackageDependenciesRequest]),
            QueryRule(GeneratedTargets, [GenerateGoExternalPackageTargetsRequest]),
        ],
        target_types=[GoPackage, GoModTarget, GoExternalPackageTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def assert_go_module_address(rule_runner: RuleRunner, target: Target, expected_address: Address):
    addresses = rule_runner.request(Addresses, [DependenciesRequest(target[Dependencies])])
    targets = rule_runner.request(Targets, [addresses])
    go_module_targets = [tgt for tgt in targets if tgt.has_field(GoModSourcesField)]
    assert len(go_module_targets) == 1
    assert go_module_targets[0].address == expected_address


def test_go_package_dependency_injection(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "go_module()\n",
            "foo/go.mod": "module foo\n",
            "foo/go.sum": "",
            "foo/pkg/BUILD": "go_package()\n",
            "foo/pkg/foo.go": "package pkg\n",
            "foo/bar/BUILD": "go_module(name='mod')\ngo_package(name='pkg')\n",
            "foo/bar/go.mod": "module bar\n",
            "foo/bar/src.go": "package bar\n",
        }
    )

    target = rule_runner.get_target(Address("foo/pkg", target_name="pkg"))
    assert_go_module_address(rule_runner, target, Address("foo"))

    target = rule_runner.get_target(Address("foo/bar", target_name="pkg"))
    assert_go_module_address(rule_runner, target, Address("foo/bar", target_name="mod"))


def test_go_package_dependency_inference(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        (
            {
                "foo/BUILD": "go_module()",
                "foo/go.mod": textwrap.dedent(
                    """\
                    module go.example.com/foo
                    go 1.17

                    require (
                        github.com/google/go-cmp v0.4.0
                    )
                    """
                ),
                "foo/go.sum": textwrap.dedent(
                    """\
                    github.com/google/go-cmp v0.4.0/go.mod h1:v8dTdLbMG2kIc/vJvl+f65V22dbkXbowE6jgT/gNBxE=
                    golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543 h1:E7g+9GITq07hpfrRu66IVDexMakfv52eLZ2CXBWiKr4=
                    golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543/go.mod h1:I/5z698sn9Ka8TeJc9MKroUUfqBBauWjQqLJ2OPfmY0=
                    """
                ),
                "foo/pkg/BUILD": "go_package()\n",
                "foo/pkg/foo.go": textwrap.dedent(
                    """\
                    package pkg
                    import "github.com/google/go-cmp/cmp"
                    func grok(left, right string) bool {
                        return cmp.Equal(left, right)
                    }
                    """
                ),
                "foo/cmd/BUILD": "go_package()\n",
                "foo/cmd/main.go": textwrap.dedent(
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
            "src/go/BUILD": "go_module()\n",
            "src/go/go.mod": textwrap.dedent(
                """\
                module example.com/src/go
                go 1.17

                require (
                    github.com/google/go-cmp v0.4.0
                    github.com/google/uuid v1.2.0
                )
                """
            ),
            "src/go/go.sum": textwrap.dedent(
                """\
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

    def gen_tgt(mod_path: str, version: str, import_path: str) -> GoExternalPackageTarget:
        return GoExternalPackageTarget(
            {
                GoExternalModulePathField.alias: mod_path,
                GoExternalModuleVersionField.alias: version,
                GoExternalPackageImportPathField.alias: import_path,
            },
            Address("src/go", generated_name=import_path),
        )

    expected = GeneratedTargets(
        generator,
        {
            gen_tgt("github.com/google/uuid", "v1.2.0", "github.com/google/uuid"),
            gen_tgt("github.com/google/go-cmp", "v0.4.0", "github.com/google/go-cmp/cmp"),
            gen_tgt("github.com/google/go-cmp", "v0.4.0", "github.com/google/go-cmp/cmp/cmpopts"),
            gen_tgt(
                "github.com/google/go-cmp", "v0.4.0", "github.com/google/go-cmp/cmp/internal/diff"
            ),
            gen_tgt(
                "github.com/google/go-cmp", "v0.4.0", "github.com/google/go-cmp/cmp/internal/flags"
            ),
            gen_tgt(
                "github.com/google/go-cmp",
                "v0.4.0",
                "github.com/google/go-cmp/cmp/internal/function",
            ),
            gen_tgt(
                "github.com/google/go-cmp",
                "v0.4.0",
                "github.com/google/go-cmp/cmp/internal/testprotos",
            ),
            gen_tgt(
                "github.com/google/go-cmp",
                "v0.4.0",
                "github.com/google/go-cmp/cmp/internal/teststructs",
            ),
            gen_tgt(
                "github.com/google/go-cmp", "v0.4.0", "github.com/google/go-cmp/cmp/internal/value"
            ),
            gen_tgt(
                "golang.org/x/xerrors", "v0.0.0-20191204190536-9bdfabe68543", "golang.org/x/xerrors"
            ),
            gen_tgt(
                "golang.org/x/xerrors",
                "v0.0.0-20191204190536-9bdfabe68543",
                "golang.org/x/xerrors/internal",
            ),
        },
    )
    assert list(generated.keys()) == list(expected.keys())
    assert generated == expected
