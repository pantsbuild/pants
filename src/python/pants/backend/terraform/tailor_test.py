# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.terraform.tailor import PutativeTerraformTargetsRequest
from pants.backend.terraform.tailor import rules as terraform_tailor_rules
from pants.backend.terraform.target_types import TerraformModule
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
            TerraformModule,
        ],
    )
    rule_runner.write_files(
        {
            f"src/terraform/{fp}": ""
            for fp in (
                "root.tf",
                "owned-module/main.tf",
                "owned-module/foo.tf",
                "unowned-module/main.tf",
                "unowned-module/bar.tf",
            )
        }
    )
    pts = rule_runner.request(
        PutativeTargets,
        [
            PutativeTerraformTargetsRequest(),
            AllOwnedSources(
                [
                    "src/terraform/root.tf",
                    "src/terraform/owned-module/main.tf",
                    "src/terraform/owned-module/foo.tf",
                ]
            ),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    TerraformModule,
                    "src/terraform",
                    "terraform",
                    [
                        "root.tf",
                    ],
                ),
                PutativeTarget.for_target_type(
                    TerraformModule,
                    "src/terraform/owned-module",
                    "owned-module",
                    [
                        "foo.tf",
                        "main.tf",
                    ],
                ),
                PutativeTarget.for_target_type(
                    TerraformModule,
                    "src/terraform/unowned-module",
                    "unowned-module",
                    [
                        "bar.tf",
                        "main.tf",
                    ],
                ),
            ]
        )
        == pts
    )
