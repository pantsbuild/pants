# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.bsp.context import BSPContext
from pants.bsp.util_rules import compile, lifecycle, targets
from pants.engine.internals.session import SessionValues
from pants.engine.rules import collect_rules, rule


@rule
async def bsp_context(session_values: SessionValues) -> BSPContext:
    return session_values[BSPContext]


def rules():
    return (
        *collect_rules(),
        *compile.rules(),
        *lifecycle.rules(),
        *targets.rules(),
    )
