# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Iterable, Iterator, List, Optional

import strawberry
from strawberry.types import Info

from pants.backend.explorer.request_state import RequestState
from pants.backend.explorer.server.field_types import JSONScalar
from pants.backend.project_info.peek import TargetData, TargetDatas
from pants.engine.target import AllTargets, UnexpandedTargets, Targets
from pants.help.help_info_extracter import TargetTypeHelpInfo
from pants.base.specs_parser import SpecsParser


specs_parser = SpecsParser()


@strawberry.type
class TargetTypeField:
    alias: str
    provider: str
    description: str
    type_hint: str
    required: bool
    default: Optional[str]


@strawberry.type
class TargetType:
    alias: str
    provider: str
    summary: str
    description: str
    fields: List[TargetTypeField]

    @classmethod
    def from_help(cls, info: TargetTypeHelpInfo) -> TargetType:
        data = asdict(info)
        data["fields"] = [TargetTypeField(**target_field) for target_field in data["fields"]]
        return cls(**data)


@strawberry.type
class Target:
    address: str
    target_type: str
    fields: JSONScalar

    @classmethod
    def from_data(cls, data: TargetData) -> Target:
        json = data.to_json()
        address = json.pop("address")
        target_type = json.pop("target_type")
        fields = json
        return cls(address=address, target_type=target_type, fields=fields)


@strawberry.input
class TargetTypesQuery:
    alias: Optional[str] = None
    limit: Optional[int] = None

    def __bool__(self) -> bool:
        return not (self.alias is None and self.limit is None)

    @staticmethod
    def filter(
        query: TargetTypesQuery | None, target_types: Iterable[TargetType]
    ) -> Iterator[TargetType]:
        if not query:
            yield from target_types
            return

        alias_pattern = query.alias and re.compile(query.alias)
        count = 0
        for info in target_types:
            if alias_pattern and not re.match(alias_pattern, info.alias):
                continue
            yield info
            count += 1
            if query.limit and count >= query.limit:
                return


@strawberry.input
class TargetsQuery:
    specs: Optional[List[str]] = None
    target_type: Optional[str] = None
    limit: Optional[int] = None

    def __bool__(self) -> bool:
        # The `specs` field is not used in the `filter` method.
        return not (self.target_type is None and self.limit is None)

    @staticmethod
    def filter(
        query: TargetsQuery | None, 
        targets: Iterable[TargetData]
    ) -> Iterator[TargetData]:
        if not query:
            yield from targets
            return

        count = 0
        for data in targets:
            if query.target_type and data.target.alias != query.target_type:
                continue
            yield data
            count += 1
            if query.limit and count >= query.limit:
                return


@strawberry.type
class QueryTargetsMixin:
    """Get targets related info."""

    @strawberry.field
    def target_types(
        self, info: Info, query: Optional[TargetTypesQuery] = None
    ) -> List[TargetType]:
        """Get all registered target types that may be used in BUILD files."""
        return list(
            TargetTypesQuery.filter(
                query,
                (
                    TargetType.from_help(info)
                    for info in RequestState.from_info(
                        info
                    ).all_help_info.name_to_target_type_info.values()
                ),
            )
        )

    @strawberry.field
    async def targets(self, info: Info, query: Optional[TargetsQuery] = None) -> List[Target]:
        """Get all targets defined in BUILD files."""
        req = RequestState.from_info(info).product_request
        specs = specs_parser.parse_specs(query.specs) if query is not None and query.specs else None
        print(f"\n\nSPECS: {specs}\n\n")
        if specs and specs.provided:
            targets = req(Targets, (specs,))
        else:
            targets = req(AllTargets)

        # Peek expects to work with unexpanded targets, but we want to present the expanded set of
        # targets, so we pretend our targets are unexpanded.
        all_data = req(TargetDatas, (UnexpandedTargets(targets),))

        return [
            Target.from_data(data)
            for data in TargetsQuery.filter(query, all_data)
        ]
