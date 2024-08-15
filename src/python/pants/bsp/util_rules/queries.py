# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from typing import Iterable

from pants.bsp.protocol import BSPHandlerMapping
from pants.engine.environment import EnvironmentName
from pants.engine.fs import Workspace
from pants.engine.rules import QueryRule, Rule
from pants.engine.unions import UnionRule


def compute_handler_query_rules(
    rules: Iterable[Rule | UnionRule | QueryRule],
) -> tuple[QueryRule, ...]:
    queries: list[QueryRule] = []

    for rule in rules:
        if isinstance(rule, UnionRule):
            if rule.union_base == BSPHandlerMapping:
                impl = rule.union_member
                assert issubclass(impl, BSPHandlerMapping)
                queries.append(
                    QueryRule(impl.response_type, (impl.request_type, Workspace, EnvironmentName))
                )

    return tuple(queries)
