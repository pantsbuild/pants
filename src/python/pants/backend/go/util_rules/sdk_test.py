# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.go.util_rules import sdk
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.engine.process import Process
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *sdk.rules(),
            QueryRule(Process, [GoSdkProcess]),
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_gotoolchain_local_is_set(rule_runner: RuleRunner) -> None:
    """GOTOOLCHAIN=local must be present in every GoSdkProcess environment."""
    process = rule_runner.request(
        Process,
        [GoSdkProcess(["version"], description="test: go version")],
    )
    assert process.env.get("GOTOOLCHAIN") == "local"


def test_gotoolchain_local_cannot_be_overridden(rule_runner: RuleRunner) -> None:
    """GOTOOLCHAIN=local must survive even when the caller passes a different value via
    GoSdkProcess(env=...).  The pin is placed after **request.env in the dict literal so
    caller-supplied values are silently overwritten."""
    process = rule_runner.request(
        Process,
        [
            GoSdkProcess(
                ["version"],
                description="test: override attempt",
                env=FrozenDict({"GOTOOLCHAIN": "auto"}),
            )
        ],
    )
    assert process.env.get("GOTOOLCHAIN") == "local"
