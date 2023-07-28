# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from random import randrange

from pants.engine.rules import Get, MultiGet, rule
from pants.testutil.rule_runner import QueryRule, RuleRunner


@dataclass(frozen=True, slots=True)
class Deep:
    val: int


@rule
async def deep(n: int) -> Deep:
    if n < 2:
        return Deep(n)
    x, y = tuple(await MultiGet([Get(Deep, int(n - 2)), Get(Deep, int(n - 1))]))
    return Deep(x.val + y.val)


@dataclass(frozen=True, slots=True)
class Wide:
    val: int


@rule
async def wide(index: int) -> Wide:
    if index > 0:
        _ = await MultiGet([Get(Wide, int(randrange(index))) for _ in range(100)])
    return Wide(index)


def test_bench_deep():
    rule_runner = RuleRunner(rules=[deep, QueryRule(Deep, (int,))])
    for _ in range(0, 10):
        rule_runner.scheduler.scheduler.invalidate_all()
        _ = rule_runner.request(Deep, [10000])


def test_bench_wide():
    rule_runner = RuleRunner(rules=[wide, QueryRule(Wide, (int,))])
    for _ in range(0, 5):
        rule_runner.scheduler.scheduler.invalidate_all()
        _ = rule_runner.request(Wide, [1000])
