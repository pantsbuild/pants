# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Iterable, Iterator, List, Optional

import strawberry
from pants_explorer.server.graphql.context import GraphQLContext
from pants_explorer.server.graphql.field_types import JSONScalar
from strawberry.types import Info

from pants.backend.project_info.peek import TargetData, TargetDatas
from pants.base.specs_parser import SpecsParser
from pants.engine.target import AllUnexpandedTargets, UnexpandedTargets
from pants.help.help_info_extracter import TargetTypeHelpInfo
from pants.util.strutil import softwrap


@strawberry.type(description="Describes a target field type.")
class TargetTypeField:
    alias: str = strawberry.field(
        description="The field name, as used in a target definition in a BUILD file."
    )
    provider: str = strawberry.field(description="Backend that registered the field type.")
    description: str = strawberry.field(description="Field documentation.")
    type_hint: str = strawberry.field(description="Field type hint.")
    required: bool = strawberry.field(description="Field required flag.")
    default: Optional[str] = strawberry.field(description="Field default value.")


@strawberry.type(description="Describes a target type.")
class TargetType:
    alias: str = strawberry.field(
        description="The target alias, as used in the BUILD files, e.g. `python_sources`."
    )
    provider: str = strawberry.field(description="Backend that registered the target type.")
    summary: str = strawberry.field(description="Target type documentation summary.")
    description: str = strawberry.field(description="Target type documentation.")
    fields: List[TargetTypeField] = strawberry.field(description="All valid fields for the target.")

    @classmethod
    def from_help(cls, info: TargetTypeHelpInfo) -> TargetType:
        data = asdict(info)
        data["fields"] = [TargetTypeField(**target_field) for target_field in data["fields"]]
        return cls(**data)


@strawberry.type(description="Describes a target defined in a project BUILD file.")
class Target:
    address: str = strawberry.field(description="The target address.")
    target_type: str = strawberry.field(
        description="The target type, such as `python_sources` or `pex_binary` etc."
    )
    fields: JSONScalar = strawberry.field(
        description=softwrap(
            """
            The targets field values. This has the same structure as the JSON output from the `peek`
            goal, i.e. some fields may be both on a `_raw` form as well as on a parsed/populated form.
            """
        )
    )

    @classmethod
    def from_data(cls, data: TargetData) -> Target:
        json = data.to_dict()
        address = json.pop("address")
        target_type = json.pop("target_type")
        fields = json
        return cls(address=address, target_type=target_type, fields=fields)


@strawberry.input(
    description="Filter target types based on type (alias) and/or limit the number of entries to return."
)
class TargetTypesQuery:
    alias_re: Optional[str] = strawberry.field(
        default=None, description="Select targets types matching a regexp."
    )
    limit: Optional[int] = strawberry.field(
        default=None, description="Limit the number of entries returned."
    )

    def __bool__(self) -> bool:
        return not (self.alias_re is None and self.limit is None)

    @staticmethod
    def filter(
        query: TargetTypesQuery | None, target_types: Iterable[TargetType]
    ) -> Iterator[TargetType]:
        if not query:
            yield from target_types
            return

        alias_pattern = query.alias_re and re.compile(query.alias_re)
        count = 0
        for info in target_types:
            if query.limit is not None and count >= query.limit:
                return
            if alias_pattern and not re.match(alias_pattern, info.alias):
                continue
            yield info
            count += 1


@strawberry.input(description="Filter targets based on the supplied query.")
class TargetsQuery:
    specs: Optional[List[str]] = strawberry.field(
        default=None,
        description=(
            "Select targets matching the address specs. (Same syntax as supported on the command line.)"
        ),
    )
    target_type: Optional[str] = strawberry.field(
        default=None, description="Select targets of a certain type only."
    )
    limit: Optional[int] = strawberry.field(
        default=None, description="Limit the number of entries returned."
    )

    def __bool__(self) -> bool:
        # The `specs` field is not used in the `filter` method.
        return not (self.target_type is None and self.limit is None)

    @staticmethod
    def filter(query: TargetsQuery | None, targets: Iterable[TargetData]) -> Iterator[TargetData]:
        if not query:
            yield from targets
            return

        count = 0
        for data in targets:
            if query.limit is not None and count >= query.limit:
                return
            if query.target_type and data.target.alias != query.target_type:
                continue
            yield data
            count += 1


@strawberry.type(description="Get targets related info.")
class QueryTargetsMixin:
    @strawberry.field(
        description="Get all registered target types that may be used in BUILD files."
    )
    def target_types(
        self, info: Info, query: Optional[TargetTypesQuery] = None
    ) -> List[TargetType]:
        request_state = GraphQLContext.request_state_from_info(info)
        return list(
            TargetTypesQuery.filter(
                query,
                (
                    TargetType.from_help(info)
                    for info in request_state.all_help_info.name_to_target_type_info.values()
                ),
            )
        )

    @strawberry.field(description="Get all targets defined in BUILD files.")
    async def targets(self, info: Info, query: Optional[TargetsQuery] = None) -> List[Target]:
        req = GraphQLContext.request_state_from_info(info).product_request
        specs = (
            SpecsParser().parse_specs(
                query.specs, description_of_origin="GraphQL targets `query.specs`"
            )
            if query is not None and query.specs
            else None
        )
        if specs:
            targets = req(UnexpandedTargets, (specs,))
        else:
            targets = UnexpandedTargets(req(AllUnexpandedTargets))
        all_data = req(TargetDatas, (targets,))
        return [Target.from_data(data) for data in TargetsQuery.filter(query, all_data)]
