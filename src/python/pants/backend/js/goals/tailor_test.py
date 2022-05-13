# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.js.goals import tailor
from pants.backend.js.goals.tailor import PutativeJSTargetsRequest
from pants.backend.js.target_types import JSSourcesGeneratorTarget
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
            QueryRule(PutativeTargets, (PutativeJSTargetsRequest, AllOwnedSources)),
        ],
        target_types=[JSSourcesGeneratorTarget],
    )


def test_find_putative_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/owned/BUILD": "js_sources()\n",
            "src/owned/OwnedFile.js": "",
            "src/unowned/UnownedFile1.js": "",
            "src/unowned/UnownedFile2.js": "",
        }
    )
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeJSTargetsRequest(PutativeTargetsSearchPaths(("",))),
            AllOwnedSources(["src/owned/OwnedFile.js"]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    JSSourcesGeneratorTarget,
                    "src/unowned",
                    "unowned",
                    ["UnownedFile1.js", "UnownedFile2.js"],
                ),
            ]
        )
        == putative_targets
    )
