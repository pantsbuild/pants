# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pathlib import PurePath

from pants.backend.terraform.goals.tailor import (
    PutativeTerraformTargetsRequest,
    find_disjoint_longest_common_prefixes,
)
from pants.backend.terraform.goals.tailor import rules as terraform_tailor_rules
from pants.backend.terraform.target_types import (
    TerraformModulesGeneratorTarget,
    TerraformModuleTarget,
)
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsSearchPaths,
)
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
            TerraformModulesGeneratorTarget,
        ],
    )
    rule_runner.write_files(
        {
            fp: ""
            for fp in (
                "prod/terraform/resources/foo/versions.tf",
                "prod/terraform/resources/bar/versions.tf",
                "prod/terraform/modules/bar/versions.tf",
                "prod/terraform/modules/bar/hello/versions.tf",
                "prod/terraform/modules/world/versions.tf",
                "service1/src/terraform/versions.tf",
                "service1/src/terraform/foo/versions.tf",
                "service1/src/terraform/versions.tf",
                "service2/src/terraform/versions.tf",
            )
        }
    )
    pts = rule_runner.request(
        PutativeTargets,
        [
            PutativeTerraformTargetsRequest(PutativeTargetsSearchPaths(("",))),
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
                    TerraformModulesGeneratorTarget,
                    "prod/terraform",
                    "tf_mods",
                    ("prod/terraform/**/*.tf",),
                ),
                PutativeTarget.for_target_type(
                    TerraformModulesGeneratorTarget,
                    "service1/src/terraform",
                    "tf_mods",
                    ("service1/src/terraform/**/*.tf",),
                ),
                PutativeTarget.for_target_type(
                    TerraformModulesGeneratorTarget,
                    "service2/src/terraform",
                    "tf_mods",
                    ("service2/src/terraform/**/*.tf",),
                ),
            ]
        )
        == pts
    )


def test_find_disjoint_longest_common_prefixes() -> None:
    paths = [
        "prod/terraform/resources/foo/versions.tf",
        "prod/terraform/resources/bar/versions.tf",
        "prod/terraform/modules/bar/versions.tf",
        "prod/terraform/modules/bar/hello/versions.tf",
        "prod/terraform/modules/world/versions.tf",
        "service1/src/terraform/versions.tf",
        "service1/src/terraform/foo/versions.tf",
        "service1/src/terraform/versions.tf",
        "service2/src/terraform/versions.tf",
    ]
    prefixes = find_disjoint_longest_common_prefixes([PurePath(p).parts[:-1] for p in paths])
    assert prefixes == {
        ("prod", "terraform"),
        ("service1", "src", "terraform"),
        ("service2", "src", "terraform"),
    }
