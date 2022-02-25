# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.bsp.context import BSPContext
from pants.bsp.util_rules.compile import rules as bsp_compile_rules
from pants.bsp.util_rules.lifecycle import rules as bsp_lifecycle_rules
from pants.bsp.util_rules.targets import rules as bsp_targets_rules
from pants.engine.internals.session import SessionValues
from pants.engine.rules import collect_rules, rule


@rule
async def bsp_context(session_values: SessionValues) -> BSPContext:
    return session_values[BSPContext]


def rules():
    return (
        *collect_rules(),
        *bsp_lifecycle_rules(),
        *bsp_targets_rules(),
        *bsp_compile_rules(),
    )
