# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.cc.goals import tailor
from pants.backend.cc.goals.tailor import PutativeCCTargetsRequest
from pants.backend.cc.target_types import CCSourcesGeneratorTarget
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsSearchPaths,
)
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *tailor.rules(),
            QueryRule(PutativeTargets, (PutativeCCTargetsRequest, AllOwnedSources)),
        ],
        target_types=[CCSourcesGeneratorTarget],
    )


def test_find_putative_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/native/owned/BUILD": "cc_sources()\n",
            "src/native/owned/OwnedFile.cc": "",
            "src/native/unowned/UnownedFile.c": "",
        }
    )
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeCCTargetsRequest(PutativeTargetsSearchPaths(("",))),
            AllOwnedSources(["src/native/owned/OwnedFile.cc"]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    CCSourcesGeneratorTarget,
                    "src/native/unowned",
                    "unowned",
                    ["UnownedFile.c"],
                ),
            ]
        )
        == putative_targets
    )
