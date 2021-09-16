# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import textwrap

import pytest

from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.terraform import dependency_inference
from pants.backend.terraform.dependency_inference import InferTerraformModuleDependenciesRequest
from pants.backend.terraform.target_types import TerraformModule
from pants.build_graph.address import Address
from pants.core.util_rules import external_tool, source_files
from pants.engine.rules import QueryRule
from pants.engine.target import InferredDependencies, Sources
from pants.testutil.rule_runner import RuleRunner
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[TerraformModule],
        rules=[
            *external_tool.rules(),
            *source_files.rules(),
            *pex_rules(),
            *dependency_inference.rules(),
            QueryRule(InferredDependencies, [InferTerraformModuleDependenciesRequest]),
        ],
    )
    rule_runner.set_options(
        ["--backend-packages=pants.backend.experimental.terraform"],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    return rule_runner


def test_dependency_inference(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/tf/modules/foo/BUILD": "terraform_module()\n",
            "src/tf/modules/foo/versions.tf": "",
            "src/tf/modules/foo/bar/BUILD": "terraform_module()\n",
            "src/tf/modules/foo/bar/versions.tf": "",
            "src/tf/resources/grok/subdir/BUILD": "terraform_module()\n",
            "src/tf/resources/grok/subdir/versions.tf": "",
            "src/tf/resources/grok/BUILD": "terraform_module()\n",
            "src/tf/resources/grok/resources.tf": textwrap.dedent(
                """\
            module "foo" {
              source = "../../modules/foo"
            }
            module "bar" {
              source = "../../modules/foo/bar"
            }
            module "subdir" {
              source = "./subdir"
            }
            # Should not be inferred as a dependency since not a local path.
            module "external" {
              source = "app.terraform.io/example-corp/k8s-cluster/azurerm"
              version = "1.1.0"
            }
            """
            ),
        }
    )

    target = rule_runner.get_target(Address("src/tf/resources/grok"))
    inferred_deps = rule_runner.request(
        InferredDependencies, [InferTerraformModuleDependenciesRequest(target.get(Sources))]
    )
    assert inferred_deps == InferredDependencies(
        FrozenOrderedSet(
            [
                Address("src/tf/modules/foo"),
                Address("src/tf/modules/foo/bar"),
                Address("src/tf/resources/grok/subdir"),
            ]
        ),
        sibling_dependencies_inferrable=False,
    )


# TODO: How can resolve_pure_path in the parser script be tested?
# def test_resolve_pure_path() -> None:
#     assert resolve_pure_path(PurePath("foo/bar/hello/world"), PurePath("../../grok")) == PurePath(
#         "foo/bar/grok"
#     )
#     assert resolve_pure_path(
#         PurePath("foo/bar/hello/world"), PurePath("../../../../grok")
#     ) == PurePath("grok")
#     with pytest.raises(ValueError):
#         resolve_pure_path(PurePath("foo/bar/hello/world"), PurePath("../../../../../grok"))
#     assert resolve_pure_path(PurePath("foo/bar/hello/world"), PurePath("./grok")) == PurePath(
#         "foo/bar/hello/world/grok"
#     )
