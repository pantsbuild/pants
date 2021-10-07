# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.go.goals.tailor import PutativeGoModuleTargetsRequest
from pants.backend.go.goals.tailor import rules as go_tailor_rules
from pants.backend.go.target_types import GoModTarget
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
            *go_tailor_rules(),
            QueryRule(PutativeTargets, [PutativeGoModuleTargetsRequest, AllOwnedSources]),
        ],
        target_types=[GoModTarget],
    )


def test_find_putative_go_mod_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/go/owned/BUILD": "go_mod()\n",
            "src/go/owned/go.mod": "module example.com/src/go/owned\n",
            "src/go/unowned/go.mod": "module example.com/src/go/unowned\n",
        }
    )
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeGoModuleTargetsRequest(PutativeTargetsSearchPaths(("src/",))),
            AllOwnedSources(["src/go/owned/go.mod"]),
        ],
    )
    assert putative_targets == PutativeTargets(
        [
            PutativeTarget.for_target_type(
                GoModTarget, path="src/go/unowned", name="unowned", triggering_sources=["go.mod"]
            )
        ]
    )
