# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.terraform.goals.tailor import PutativeTerraformTargetsRequest
from pants.backend.terraform.goals.tailor import rules as terraform_tailor_rules
from pants.backend.terraform.target_types import (
    TerraformBackendTarget,
    TerraformModuleTarget,
    TerraformVarFileTarget,
)
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.core.goals.tailor import rules as core_tailor_rules
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


def test_find_putative_targets() -> None:
    rule_runner = RuleRunner(
        rules=[
            *core_tailor_rules(),
            *terraform_tailor_rules(),
            QueryRule(PutativeTargets, [PutativeTerraformTargetsRequest, AllOwnedSources]),
            QueryRule(AllOwnedSources, ()),
        ],
        target_types=[
            TerraformModuleTarget,
        ],
    )
    rule_runner.write_files(
        {
            "prod/terraform/owned-module/BUILD": "terraform_module()",
            "prod/terraform/owned-module/versions.tf": "",
            "prod/terraform/unowned-module/versions.tf": "",
            "prod/terraform/unowned-module/prod0.tfbackend": "",
            "prod/terraform/unowned-module/prod1.tfbackend": "",
            "prod/terraform/unowned-module/prod0.tfvars": "",
            "prod/terraform/unowned-module/prod1.tfvars": "",
        }
    )
    pts = rule_runner.request(
        PutativeTargets,
        [
            PutativeTerraformTargetsRequest(
                ("prod/terraform/owned-module", "prod/terraform/unowned-module")
            ),
            AllOwnedSources(["prod/terraform/owned-module/versions.tf"]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    TerraformModuleTarget,
                    "prod/terraform/unowned-module",
                    "unowned-module",
                    ("versions.tf",),
                ),
                PutativeTarget.for_target_type(
                    TerraformBackendTarget,
                    "prod/terraform/unowned-module",
                    "unowned-module",
                    ("prod0.tfbackend",),
                ),
                PutativeTarget.for_target_type(
                    TerraformBackendTarget,
                    "prod/terraform/unowned-module",
                    "unowned-module",
                    ("prod1.tfbackend",),
                ),
                PutativeTarget.for_target_type(
                    TerraformVarFileTarget,
                    "prod/terraform/unowned-module",
                    "unowned-module",
                    ("prod0.tfvars",),
                ),
                PutativeTarget.for_target_type(
                    TerraformVarFileTarget,
                    "prod/terraform/unowned-module",
                    "unowned-module",
                    ("prod1.tfvars",),
                ),
            ]
        )
        == pts
    )
