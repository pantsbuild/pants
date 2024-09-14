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


@dataclass(frozen=True)
class WrapperUsingCallByNameRequest:
    pass


@rule
async def wrapper_using_call_by_name(request: WrapperUsingCallByNameRequest) -> int:
    return await original_rule(IntRequest())


def test_delete() -> None:
    rule_runner = RuleRunner(
        target_types=[],
        rules=[
            *collect_rules(
                {
                    "original_rule": original_rule,
                    "wrapper_using_call_by_name": wrapper_using_call_by_name,
                }
            ),
            QueryRule(int, [WrapperUsingCallByNameRequest]),
        ],
    )

    result = rule_runner.request(int, [WrapperUsingCallByNameRequest()])
    assert result == 0

    rule_runner = RuleRunner(
        target_types=[],
        rules=[
            *collect_rules(
                {
                    "original_rule": original_rule,
                    "wrapper_using_call_by_name": wrapper_using_call_by_name,
                    "new_rule": new_rule,
                }
            ),
            DeleteRule.create(original_rule),
            QueryRule(int, [WrapperUsingCallByNameRequest]),
        ],
    )

    result = rule_runner.request(int, [WrapperUsingCallByNameRequest()])
    assert result == 42
