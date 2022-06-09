# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.swift.goals import tailor
from pants.backend.swift.goals.tailor import PutativeSwiftTargetsRequest
from pants.backend.swift.target_types import SwiftSourcesGeneratorTarget
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *tailor.rules(),
            QueryRule(PutativeTargets, (PutativeSwiftTargetsRequest, AllOwnedSources)),
        ],
        target_types=[SwiftSourcesGeneratorTarget],
    )


def test_find_putative_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/owned/BUILD": "swift_sources()\n",
            "src/owned/OwnedFile.swift": "",
            "src/unowned/UnownedFile1.swift": "",
            "src/unowned/UnownedFile2.swift": "",
        }
    )
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeSwiftTargetsRequest(("src/owned", "src/unowned")),
            AllOwnedSources(["src/owned/OwnedFile.swift"]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    SwiftSourcesGeneratorTarget,
                    "src/unowned",
                    "unowned",
                    ["UnownedFile1.swift", "UnownedFile2.swift"],
                ),
            ]
        )
        == putative_targets
    )
