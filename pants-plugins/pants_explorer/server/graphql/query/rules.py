# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Iterable, Iterator, List, Optional, cast

import strawberry
from pants_explorer.server.graphql.context import GraphQLContext
from strawberry.types import Info

from pants.help import help_info_extracter


@strawberry.type(description=cast(str, help_info_extracter.RuleInfo.__doc__))
class RuleInfo:
    name: str
    description: Optional[str]
    documentation: Optional[str]
    provider: str
    output_type: str
    input_types: List[str]
    input_gets: List[str]

    @classmethod
    def from_help(cls, info: help_info_extracter.RuleInfo) -> RuleInfo:
        data = asdict(info)
        return cls(**data)


@strawberry.input(
    description="Filter rules based on name and/or limit the number of entries to return."
)
class RulesQuery:
    name_re: Optional[str] = strawberry.field(
        default=None, description="Select rules matching a regexp."
    )
    limit: Optional[int] = strawberry.field(
        default=None, description="Limit the number of entries returned."
    )

    def __bool__(self) -> bool:
        return not (self.name_re is None and self.limit is None)

    @staticmethod
    def filter(query: RulesQuery | None, rules: Iterable[RuleInfo]) -> Iterator[RuleInfo]:
        if not query:
            yield from rules
            return

        name_pattern = query.name_re and re.compile(query.name_re)
        count = 0
        for info in rules:
            if query.limit is not None and count >= query.limit:
                return
            if name_pattern and not re.search(name_pattern, info.name):
                continue
            yield info
            count += 1


@strawberry.type
class QueryRulesMixin:
    """Get rules related info."""

    @strawberry.field
    def rules(self, info: Info, query: Optional[RulesQuery] = None) -> List[RuleInfo]:
        request_state = GraphQLContext.request_state_from_info(info)
        return list(
            RulesQuery.filter(
                query,
                (
                    RuleInfo.from_help(info)
                    for info in request_state.all_help_info.name_to_rule_info.values()
                ),
            )
        )
