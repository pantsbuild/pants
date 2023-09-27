# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.core.goals.repl import Repl, ReplImplementation, ReplRequest
from pants.core.goals.repl import rules as repl_rules
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.rules import Get, rule
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner, mock_console


class MockRepl(ReplImplementation):
    name = "mock"
    supports_args = False


@rule
async def create_mock_repl_request(repl: MockRepl) -> ReplRequest:
    digest = await Get(Digest, CreateDigest([FileContent("repl.sh", b"exit 0")]))
    return ReplRequest(
        digest=digest,
        args=("/bin/bash", "repl.sh"),
        run_in_workspace=False,
    )


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=(*repl_rules(), create_mock_repl_request, UnionRule(ReplImplementation, MockRepl)),
    )


def test_valid_repl(rule_runner: RuleRunner) -> None:
    with mock_console(rule_runner.options_bootstrapper):
        result = rule_runner.run_goal_rule(Repl, args=[f"--shell={MockRepl.name}"])
    assert result.exit_code == 0


def test_unrecognized_repl(rule_runner: RuleRunner) -> None:
    with mock_console(rule_runner.options_bootstrapper):
        result = rule_runner.run_goal_rule(Repl, args=["--shell=bogus-repl"])
    assert result.exit_code == -1
    assert "'bogus-repl' is not a registered REPL. Available REPLs" in result.stderr
