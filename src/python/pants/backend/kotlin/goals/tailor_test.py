# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.kotlin.goals import tailor
from pants.backend.kotlin.goals.tailor import PutativeKotlinTargetsRequest
from pants.backend.kotlin.target_types import KotlinSourcesGeneratorTarget
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *tailor.rules(),
            QueryRule(PutativeTargets, (PutativeKotlinTargetsRequest, AllOwnedSources)),
        ],
        target_types=[KotlinSourcesGeneratorTarget],
    )


def test_find_putative_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/kotlin/owned/BUILD": "kotlin_sources()\n",
            "src/kotlin/owned/OwnedFile.kt": "package owned",
            "src/kotlin/unowned/UnownedFile.kt": "package unowned\n",
        }
    )
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeKotlinTargetsRequest(("src/kotlin/owned", "src/kotlin/unowned")),
            AllOwnedSources(["src/kotlin/owned/OwnedFile.kt"]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    KotlinSourcesGeneratorTarget,
                    "src/kotlin/unowned",
                    "unowned",
                    ["UnownedFile.kt"],
                ),
            ]
        )
        == putative_targets
    )
