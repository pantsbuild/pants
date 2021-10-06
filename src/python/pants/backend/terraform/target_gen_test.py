# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.terraform import target_gen
from pants.backend.terraform.target_gen import GenerateTerraformModuleTargetsRequest
from pants.backend.terraform.target_types import (
    TerraformModulesGeneratorTarget,
    TerraformModuleSourcesField,
    TerraformModuleTarget,
)
from pants.core.util_rules import external_tool, source_files
from pants.engine.addresses import Address
from pants.engine.rules import QueryRule
from pants.engine.target import GeneratedTargets
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[TerraformModuleTarget, TerraformModulesGeneratorTarget],
        rules=[
            *external_tool.rules(),
            *source_files.rules(),
            *target_gen.rules(),
            QueryRule(GeneratedTargets, [GenerateTerraformModuleTargetsRequest]),
        ],
    )
    rule_runner.set_options(["--backend-packages=pants.backend.experimental.terraform"])
    return rule_runner


def test_target_generation(rule_runner: RuleRunner) -> None:
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
    targets = rule_runner.request(
        GeneratedTargets, [GenerateTerraformModuleTargetsRequest(generator)]
    )
    assert targets == GeneratedTargets(
        generator,
        [
            TerraformModuleTarget(
                {TerraformModuleSourcesField.alias: ("src/tf/foo/versions.tf",)},
                generator_addr.create_generated("src/tf/foo"),
            ),
            TerraformModuleTarget(
                {TerraformModuleSourcesField.alias: ("src/tf/outputs.tf", "src/tf/versions.tf")},
                generator_addr.create_generated("src/tf"),
            ),
        ],
    )
