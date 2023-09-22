# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from random import randrange

from pants.engine.rules import Get, MultiGet, rule
from pants.testutil.rule_runner import QueryRule, RuleRunner


@dataclass(frozen=True)
class Input:
    val: int


@dataclass(frozen=True)
class Deep:
    val: int


@rule
async def deep(n: Input) -> Deep:
    if n.val < 2:
        return Deep(n.val)
    x, y = tuple(await MultiGet([Get(Deep, Input(n.val - 2)), Get(Deep, Input(n.val - 1))]))
    return Deep(x.val + y.val)


@dataclass(frozen=True)
class Wide:
    val: int


@rule
async def wide(index: Input) -> Wide:
    if index.val > 0:
        _ = await MultiGet([Get(Wide, Input(randrange(index.val))) for _ in range(100)])
    return Wide(index.val)


def test_bench_deep():
    rule_runner = RuleRunner(rules=[deep, QueryRule(Deep, (Input,))])
    for _ in range(0, 10):
        rule_runner.scheduler.scheduler.invalidate_all()
        _ = rule_runner.request(Deep, [Input(1000)])


def test_bench_wide():
    rule_runner = RuleRunner(rules=[wide, QueryRule(Wide, (Input,))])
    for _ in range(0, 5):
        rule_runner.scheduler.scheduler.invalidate_all()
        _ = rule_runner.request(Wide, [Input(1000)])
