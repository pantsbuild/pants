# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass

from pants.engine.rules import DeleteRule, collect_rules, rule
from pants.testutil.rule_runner import QueryRule, RuleRunner


@dataclass(frozen=True)
class IntRequest:
    pass


@rule
async def original_rule(request: IntRequest) -> int:
    return 0


@rule
def new_rule(request: IntRequest) -> int:
    return 42


def test_delete() -> None:
    rule_runner = RuleRunner(
        target_types=[],
        rules=[
            *collect_rules(
                {
                    "original_rule": original_rule,
                }
            ),
            QueryRule(int, [IntRequest]),
        ],
    )

    result = rule_runner.request(int, [IntRequest()])
    assert result == 0

    rule_runner = RuleRunner(
        target_types=[],
        rules=[
            *collect_rules(
                {
                    "original_rule": original_rule,
                    "new_rule": new_rule,
                }
            ),
            DeleteRule.create(original_rule),
            QueryRule(int, [IntRequest]),
        ],
    )

    result = rule_runner.request(int, [IntRequest()])
    assert result == 42
