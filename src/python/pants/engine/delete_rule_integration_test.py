# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass

from pants.engine.rules import DeleteRule, collect_rules, rule
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.engine.rules import Get
import pytest


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
class WrapperUsingCallByTypeRequest:
    pass


@rule
async def wrapper_using_call_by_type(request: WrapperUsingCallByTypeRequest) -> int:
    return await Get(int, IntRequest())


@dataclass(frozen=True)
class WrapperUsingCallByNameRequest:
    pass


@rule
async def wrapper_using_call_by_name(request: WrapperUsingCallByNameRequest) -> int:
    return await original_rule(IntRequest())


def test_delete_call_by_type() -> None:
    rule_runner = RuleRunner(
        target_types=[],
        rules=[
            *collect_rules(
                {
                    "original_rule": original_rule,
                    "wrapper_using_call_by_type": wrapper_using_call_by_type,
                }
            ),
            QueryRule(int, [WrapperUsingCallByTypeRequest]),
        ],
    )

    result = rule_runner.request(int, [WrapperUsingCallByTypeRequest()])
    assert result == 0

    rule_runner = RuleRunner(
        target_types=[],
        rules=[
            *collect_rules(
                {
                    "original_rule": original_rule,
                    "wrapper_using_call_by_type": wrapper_using_call_by_type,
                    "new_rule": new_rule,
                }
            ),
            DeleteRule.create(original_rule),
            QueryRule(int, [WrapperUsingCallByTypeRequest]),
        ],
    )

    result = rule_runner.request(int, [WrapperUsingCallByTypeRequest()])
    assert result == 42

    assert 0


def test_delete_call_by_name() -> None:
    # rule_runner = RuleRunner(
    #     target_types=[],
    #     rules=[
    #         *collect_rules(
    #             {
    #                 "original_rule": original_rule,
    #                 "wrapper_using_call_by_name": wrapper_using_call_by_name,
    #             }
    #         ),
    #         QueryRule(int, [WrapperUsingCallByNameRequest]),
    #     ],
    # )

    # result = rule_runner.request(int, [WrapperUsingCallByNameRequest()])
    # assert result == 0

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
