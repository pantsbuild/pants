# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import List

import strawberry
from strawberry.types import Info

from pants.backend.explorer.graphql.context import GraphQLContext
from pants.engine.rules import TaskRule


@strawberry.type
class RuleInfo:
    names: List[str]


@strawberry.type
class QueryRulesMixin:
    """Get rules related info."""

    @strawberry.field
    def rules(self, info: Info) -> RuleInfo:
        request_state = GraphQLContext.request_state_from_info(info)
        return RuleInfo(
            names=sorted(
                rule.canonical_name
                for rule in request_state.build_configuration.rule_to_providers.keys()
                if isinstance(rule, TaskRule)
            )
        )
