# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from random import randrange

from pants.engine.rules import Get, MultiGet, rule
from pants.testutil.rule_runner import QueryRule, RuleRunner


@dataclass(frozen=True)
class Wide:
    val: int


@rule
async def wide(index: int) -> Wide:
    if index > 0:
        _ = await MultiGet([Get(Wide, int(randrange(index))) for _ in range(100)])
    return Wide(index)


@dataclass(frozen=True)
class Fib:
    val: int


@rule
async def fib(n: int) -> Fib:
    if n < 2:
        return Fib(n)
    x, y = tuple(await MultiGet([Get(Fib, int(n - 2)), Get(Fib, int(n - 1))]))
    return Fib(x.val + y.val)


def test_bench_deep():
    rule_runner = RuleRunner(rules=[fib, QueryRule(Fib, (int,))])
    for _ in range(0, 10):
        rule_runner.scheduler.scheduler.invalidate_all()
        _ = rule_runner.request(Fib, [10000])


def test_bench_wide():
    rule_runner = RuleRunner(rules=[wide, QueryRule(Wide, (int,))])
    for _ in range(0, 5):
        rule_runner.scheduler.scheduler.invalidate_all()
        _ = rule_runner.request(Wide, [1000])
