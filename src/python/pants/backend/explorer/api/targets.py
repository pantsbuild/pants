# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import asdict
from typing import List, Optional

import strawberry
from strawberry.types import Info

from pants.backend.explorer.request_state import RequestState
from pants.engine.target import AllTargets
from pants.help.help_info_extracter import TargetTypeHelpInfo


@strawberry.type
class TargetField:
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
    fields: List[TargetField]

    @classmethod
    def from_help(cls, info: TargetTypeHelpInfo) -> TargetType:
        data = asdict(info)
        data["fields"] = [TargetField(**target_field) for target_field in data["fields"]]
        return cls(**data)


@strawberry.type
class QueryTargetsMixin:
    """Get targets related info."""

    @strawberry.field
    def target_types(self, info: Info) -> List[TargetType]:
        return [
            TargetType.from_help(info)
            for info in RequestState.from_info(info).all_help_info.name_to_target_type_info.values()
        ]

    @strawberry.field
    async def targets(self, info: Info) -> List[str]:
        all_targets = RequestState.from_info(info).product_request(AllTargets)
        return sorted(str(target.address) for target in all_targets)
