# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from typing import Iterable

from pants.backend.cc.target_types import CCFieldSet
from pants.backend.cc.util_rules.compile import CompileCCSourceRequest, FallibleCompiledCCObject
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.engine.addresses import Addresses
from pants.engine.rules import Get, MultiGet, Rule, collect_rules, rule
from pants.engine.target import CoarsenedTargets, WrappedTarget, WrappedTargetRequest
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class CCCheckRequest(CheckRequest):
    field_set_type = CCFieldSet
    name = "cc-compile"


@rule(desc="Check CC compilation", level=LogLevel.DEBUG)
async def check_cc(request: CCCheckRequest) -> CheckResults:
    logger.warning(f"FieldSets: {request.field_sets}")

    logger.warning(f"FieldSet Sources: {[field_set.sources for field_set in request.field_sets]}")
    coarsened_targets = await Get(
        CoarsenedTargets, Addresses(field_set.address for field_set in request.field_sets)
    )
    logger.warning([list(ct.closure()) for ct in coarsened_targets])
    wrapped_targets = await MultiGet(
        Get(
            WrappedTarget,
            WrappedTargetRequest(field_set.address, description_of_origin="<build_pkg_target.py>"),
        )
        for field_set in request.field_sets
    )
    logger.warning(wrapped_targets)

    compile_results = await MultiGet(
        Get(FallibleCompiledCCObject, CompileCCSourceRequest(field_set.sources))
        for field_set in request.field_sets
    )
    logger.info(compile_results)

    # NB: We don't pass stdout/stderr as it will have already been rendered as streaming.
    exit_code = next(
        (
            result.process_result.exit_code
            for result in compile_results
            if result.process_result.exit_code != 0
        ),
        0,
    )
    return CheckResults([CheckResult(exit_code, "", "")], checker_name=request.name)


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        UnionRule(CheckRequest, CCCheckRequest),
    )
