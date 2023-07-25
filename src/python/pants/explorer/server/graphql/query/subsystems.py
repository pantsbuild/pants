# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from dataclasses import asdict
from enum import Enum
from typing import Any, Iterable, Iterator, List, Mapping, Optional, cast

import strawberry
from strawberry.types import Info

from pants.explorer.server.graphql.context import GraphQLContext
from pants.help import help_info_extracter
from pants.option import parser, ranked_value


@strawberry.enum
class Rank(Enum):
    NONE = "NONE"
    HARDCODED = "HARDCODED"
    CONFIG_DEFAULT = "CONFIG_DEFAULT"
    CONFIG = "CONFIG"
    ENVIRONMENT = "ENVIRONMENT"
    FLAG = "FLAG"


@strawberry.type(description=cast(str, ranked_value.RankedValue.__doc__))
class RankedValue:
    rank: Rank
    value: str
    details: Optional[str]

    @classmethod
    def from_help(cls, value: ranked_value.RankedValue | Mapping[str, Any]) -> RankedValue:
        if isinstance(value, ranked_value.RankedValue):
            data = asdict(value)
        else:
            data = dict(value)
        data["rank"] = Rank(data["rank"].value)
        data["value"] = repr(data["value"])
        return cls(**data)


@strawberry.type
class OptionValueHistory:
    ranked_values: List[RankedValue]

    @classmethod
    def from_help(
        cls, history: parser.OptionValueHistory | Mapping[str, Any] | None
    ) -> OptionValueHistory | None:
        if history is None:
            return None
        if isinstance(history, parser.OptionValueHistory):
            data = asdict(history)
        else:
            data = dict(history)
        data["ranked_values"] = [RankedValue.from_help(ranked) for ranked in data["ranked_values"]]
        return cls(**data)


@strawberry.enum
class OptionKind(Enum):
    ADVANCED = "advanced"
    BASIC = "basic"
    DEPRECATED = "deprecated"


@strawberry.type(description=cast(str, help_info_extracter.OptionHelpInfo.__doc__))
class OptionInfo:
    kind: OptionKind
    display_args: List[str]
    comma_separated_display_args: str
    scoped_cmd_line_args: List[str]
    unscoped_cmd_line_args: List[str]
    env_var: str
    config_key: str
    target_field_name: Optional[str]
    typ: str
    default: str
    help: str
    deprecation_active: bool
    deprecated_message: Optional[str]
    removal_version: Optional[str]
    removal_hint: Optional[str]
    choices: Optional[List[str]]
    comma_separated_choices: Optional[str]
    value_history: Optional[OptionValueHistory]
    fromfile: bool

    @classmethod
    def from_help(
        cls, kind: OptionKind, info: help_info_extracter.OptionHelpInfo | Mapping[str, Any]
    ) -> OptionInfo:
        if isinstance(info, help_info_extracter.OptionHelpInfo):
            data = asdict(info)
        else:
            data = dict(info)
        data["typ"] = data["typ"].__name__
        data["default"] = repr(data["default"])
        data["value_history"] = OptionValueHistory.from_help(data["value_history"])
        return cls(kind=kind, **data)


@strawberry.type(description=cast(str, help_info_extracter.OptionScopeHelpInfo.__doc__))
class SubsystemInfo:
    scope: str
    description: str
    provider: str
    is_goal: bool
    deprecated_scope: Optional[str]
    options: List[OptionInfo]

    @classmethod
    def from_help(cls, info: help_info_extracter.OptionScopeHelpInfo) -> SubsystemInfo:
        data = asdict(info)
        data["options"] = [
            OptionInfo.from_help(kind, ohi) for kind in OptionKind for ohi in data.pop(kind.value)
        ]
        if not data["scope"]:
            data["scope"] = "GLOBAL"
        return cls(**data)


@strawberry.input(
    description="Filter subsystems based on scope and/or limit the number of entries to return."
)
class SubsystemsQuery:
    scope_re: Optional[str] = strawberry.field(
        default=None, description="Select subsystems matching a regexp."
    )
    limit: Optional[int] = strawberry.field(
        default=None, description="Limit the number of entries returned."
    )

    def __bool__(self) -> bool:
        return not (self.scope_re is None and self.limit is None)

    @staticmethod
    def filter(
        query: SubsystemsQuery | None, subsystems: Iterable[SubsystemInfo]
    ) -> Iterator[SubsystemInfo]:
        if not query:
            yield from subsystems
            return

        scope_pattern = query.scope_re and re.compile(query.scope_re)
        count = 0
        for info in subsystems:
            if query.limit is not None and count >= query.limit:
                return
            if scope_pattern and not re.search(scope_pattern, info.scope):
                continue
            yield info
            count += 1


@strawberry.type
class QuerySubsystemsMixin:
    """Get subsystems related info."""

    @strawberry.field
    def subsystems(
        self, info: Info, query: Optional[SubsystemsQuery] = None
    ) -> List[SubsystemInfo]:
        request_state = GraphQLContext.request_state_from_info(info)
        return list(
            SubsystemsQuery.filter(
                query,
                (
                    SubsystemInfo.from_help(info)
                    for info in request_state.all_help_info.scope_to_help_info.values()
                ),
            )
        )
