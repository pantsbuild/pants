# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable

from pants.backend.cc.target_types import CCFieldSet
from pants.core.goals.check import CheckRequest, CheckResults
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


class CCCheckRequest(CheckRequest):
    field_set_type = CCFieldSet
    name = "cc-compile"


@rule(desc="Check CC compilation", level=LogLevel.DEBUG)
async def check_cc(request: CCCheckRequest) -> CheckResults:
    pass


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        UnionRule(CheckRequest, CCCheckRequest),
    )
