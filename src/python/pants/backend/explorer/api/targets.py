# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import asdict
from typing import List, Optional

import strawberry
from strawberry.types import Info

from pants.backend.explorer.api.field_types import JSONScalar
from pants.backend.explorer.request_state import RequestState
from pants.backend.project_info.peek import TargetData, TargetDatas
from pants.engine.target import AllTargets, UnexpandedTargets
from pants.help.help_info_extracter import TargetTypeHelpInfo


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


@strawberry.type
class QueryTargetsMixin:
    """Get targets related info."""

    @strawberry.field
    def target_types(self, info: Info) -> List[TargetType]:
        """Get all registered target types that may be used in BUILD files."""
        return [
            TargetType.from_help(info)
            for info in RequestState.from_info(info).all_help_info.name_to_target_type_info.values()
        ]

    @strawberry.field
    async def targets(self, info: Info) -> List[Target]:
        """Get all targets defined in BUILD files."""
        req = RequestState.from_info(info).product_request
        # Peek expects to work with unexpanded targets, but we want to present the expanded set of
        # targets.
        all_data = req(TargetDatas, (UnexpandedTargets(req(AllTargets)),))
        return [Target.from_data(data) for data in all_data]
