# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.bsp.context import BSPContext
from pants.bsp.util_rules import compile, lifecycle, resources, targets
from pants.bsp.util_rules.queries import compute_handler_query_rules
from pants.engine.internals.session import SessionValues
from pants.engine.rules import collect_rules, rule


@rule
async def bsp_context(session_values: SessionValues) -> BSPContext:
    return session_values[BSPContext]


def rules():
    base_rules = (
        *collect_rules(),
        *compile.rules(),
        *lifecycle.rules(),
        *resources.rules(),
        *targets.rules(),
    )

    return (*base_rules, *compute_handler_query_rules(base_rules))
