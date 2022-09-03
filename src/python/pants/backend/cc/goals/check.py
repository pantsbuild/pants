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
    logger.debug(request.field_sets)

    # Filter out header files from Check processes
    source_file_field_sets = [
        field_set
        for field_set in request.field_sets
        if _source_file_extension(field_set) in CC_SOURCE_FILE_EXTENSIONS
    ]

    compile_results = await MultiGet(
        Get(FallibleCompiledCCObject, CompileCCSourceRequest(field_set))
        for field_set in source_file_field_sets
    )

    # For some reason, using the commented out code wasn't returning the actual errors
    return CheckResults(
        [
            CheckResult(
                result.process_result.exit_code,
                str(result.process_result.stdout),
                str(result.process_result.stderr),
            )
            for result in compile_results
        ],
        checker_name=request.name,
    )


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        UnionRule(CheckRequest, CCCheckRequest),
    )
