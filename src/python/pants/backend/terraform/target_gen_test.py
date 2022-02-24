# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.terraform import target_gen
from pants.backend.terraform.target_types import (
    TerraformModulesGeneratorTarget,
    TerraformModuleSourcesField,
    TerraformModuleTarget,
)
from pants.core.util_rules import external_tool
from pants.engine.addresses import Address
from pants.engine.internals.graph import _TargetParametrizations
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[TerraformModuleTarget, TerraformModulesGeneratorTarget],
        rules=[
            *external_tool.rules(),
            *target_gen.rules(),
            QueryRule(_TargetParametrizations, [Address]),
        ],
    )


def test_target_generation_at_build_root(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "terraform_modules(name='tf_mods')\n",
            "src/tf/versions.tf": "",
            "src/tf/outputs.tf": "",
            "src/tf/foo/versions.tf": "",
            "src/tf/not-terraform/README.md": "This should not trigger target generation.",
        }
    )

    generator_addr = Address("", target_name="tf_mods")
    generator = rule_runner.get_target(generator_addr)
    targets = rule_runner.request(_TargetParametrizations, [generator.address])
    assert set(targets.parametrizations.values()) == {
        TerraformModuleTarget(
            {TerraformModuleSourcesField.alias: ("src/tf/foo/versions.tf",)},
            generator_addr.create_generated("src/tf/foo"),
            residence_dir="src/tf/foo",
        ),
        TerraformModuleTarget(
            {TerraformModuleSourcesField.alias: ("src/tf/outputs.tf", "src/tf/versions.tf")},
            generator_addr.create_generated("src/tf"),
            residence_dir="src/tf",
        ),
    }


def test_target_generation_at_subdir(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/tf/BUILD": "terraform_modules()\n",
            "src/tf/versions.tf": "",
            "src/tf/foo/versions.tf": "",
        }
    )

    generator_addr = Address("src/tf")
    generator = rule_runner.get_target(generator_addr)
    targets = rule_runner.request(_TargetParametrizations, [generator.address])
    assert set(targets.parametrizations.values()) == {
        TerraformModuleTarget(
            {TerraformModuleSourcesField.alias: ("foo/versions.tf",)},
            generator_addr.create_generated("foo"),
            residence_dir="src/tf/foo",
        ),
        TerraformModuleTarget(
            {TerraformModuleSourcesField.alias: ("versions.tf",)},
            generator_addr.create_generated("."),
            residence_dir="src/tf",
        ),
    }
