# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.engine.internals.native_engine import PyNgInvocation
from pants.engine.internals.session import SessionValues
from pants.engine.rules import Rule, _uncacheable_rule, collect_rules, implicitly, rule


@dataclass(frozen=True)
class PassthruArgs:
    # Args passed to Pants after `--` and intended to be passed through to an underlying tool.
    args: tuple[str, ...] | None


@_uncacheable_rule
async def get_ng_invocation(session_values: SessionValues) -> PyNgInvocation:
    return session_values[PyNgInvocation]


@rule
async def get_passthru_args() -> PassthruArgs:
    invocation = await get_ng_invocation(**implicitly())
    return PassthruArgs(invocation.passthru())


def rules() -> tuple[Rule, ...]:
    return (*collect_rules(),)
