# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from pathlib import PurePath
from typing import Iterable

from pants.backend.cc.target_types import CC_SOURCE_FILE_EXTENSIONS, CCFieldSet
from pants.backend.cc.util_rules.compile import CompileCCSourceRequest, FallibleCompiledCCObject
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.engine.rules import Get, MultiGet, Rule, collect_rules, rule
from pants.engine.target import WrappedTarget, WrappedTargetRequest
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class CCCheckRequest(CheckRequest):
    field_set_type = CCFieldSet
    name = "cc-compile"


def _source_file_extension(field_set: CCFieldSet) -> str:
    path = PurePath(field_set.sources.value)
    return path.suffix


@rule(desc="Check CC compilation", level=LogLevel.DEBUG)
async def check_cc(request: CCCheckRequest) -> CheckResults:
    logger.error(request.field_sets)

    # Filter out header files from Check processes
    source_file_field_sets = [
        field_set
        for field_set in request.field_sets
        if _source_file_extension(field_set) in CC_SOURCE_FILE_EXTENSIONS
    ]

    # TODO: Should this be a target?
    wrapped_targets = await MultiGet(
        Get(
            WrappedTarget,
            WrappedTargetRequest(field_set.address, description_of_origin="<build_pkg_target.py>"),
        )
        for field_set in source_file_field_sets
    )

    # TODO: Should we pass targets? Or field sets? Or single source files?
    compile_results = await MultiGet(
        Get(FallibleCompiledCCObject, CompileCCSourceRequest(wrapped_target.target))
        for wrapped_target in wrapped_targets
    )

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
