# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Iterable, Iterator, List, Optional, cast

import strawberry
from strawberry.types import Info

from pants.explorer.server.graphql.context import GraphQLContext
from pants.help import help_info_extracter


@strawberry.type(description=cast(str, help_info_extracter.BackendHelpInfo.__doc__))
class BackendInfo:
    name: str
    description: str
    enabled: bool
    provider: str

    @classmethod
    def from_help(cls, info: help_info_extracter.BackendHelpInfo) -> BackendInfo:
        data = asdict(info)
        return cls(**data)


@strawberry.input(
    description="Filter backends based on name and/or limit the number of entries to return."
)
class BackendsQuery:
    name_re: Optional[str] = strawberry.field(
        default=None, description="Select backends matching a regexp."
    )
    limit: Optional[int] = strawberry.field(
        default=None, description="Limit the number of entries returned."
    )

    def __bool__(self) -> bool:
        return not (self.name_re is None and self.limit is None)

    @staticmethod
    def filter(query: BackendsQuery | None, types: Iterable[BackendInfo]) -> Iterator[BackendInfo]:
        if not query:
            yield from types
            return

        name_pattern = query.name_re and re.compile(query.name_re)
        count = 0
        for info in types:
            if query.limit is not None and count >= query.limit:
                return
            if name_pattern and not re.search(name_pattern, info.name):
                continue
            yield info
            count += 1


@strawberry.type
class QueryBackendsMixin:
    """Get backends related info."""

    @strawberry.field
    def backends(self, info: Info, query: Optional[BackendsQuery] = None) -> List[BackendInfo]:
        request_state = GraphQLContext.request_state_from_info(info)
        return list(
            BackendsQuery.filter(
                query,
                (
                    BackendInfo.from_help(info)
                    for info in request_state.all_help_info.name_to_backend_help_info.values()
                ),
            )
        )
