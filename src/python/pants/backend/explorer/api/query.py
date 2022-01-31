# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import List

import strawberry
from strawberry.types import Info

from pants.backend.explorer.request_state import RequestState
from pants.engine.rules import TaskRule
from pants.engine.target import AllTargets


@strawberry.type
class RuleInfo:
    names: List[str]


@strawberry.type
class Query:
    """Access to Pantsbuild data."""

    @strawberry.field
    def rules(self, info: Info) -> RuleInfo:
        return RuleInfo(
            names=sorted(
                rule.canonical_name
                for rule in RequestState.from_info(
                    info
                ).build_configuration.rule_to_providers.keys()
                if isinstance(rule, TaskRule)
            )
        )

    @strawberry.field
    async def targets(self, info: Info) -> List[str]:
        all_targets = RequestState.from_info(info).product_request(AllTargets)
        return sorted(str(target.address) for target in all_targets)
