# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from itertools import groupby
from typing import Iterable

from pants.backend.swift.subsystems.toolchain import SwiftSubsystem
from pants.backend.swift.target_types import SwiftFieldSet, SwiftSourceField
from pants.backend.swift.util_rules.compile import (
    FallibleTypecheckedSwiftModule,
    TypecheckSwiftModuleRequest,
)
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.engine.rules import Get, MultiGet, Rule, collect_rules, rule
from pants.engine.target import AllTargets, AllTargetsRequest
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class SwiftCheckRequest(CheckRequest):
    field_set_type = SwiftFieldSet
    name = SwiftSubsystem.options_scope


@rule(desc="Typecheck Swift compilation", level=LogLevel.DEBUG)
async def swift_typecheck(request: SwiftCheckRequest) -> CheckResults:
    # Retrieve the sources targets (swift modules) represented by the check request
    # Checking a single-file could fail, because it's missing context from other files in the module - so typecheck the module
    # More importantly, changing a single file could cause failures in other files in that module

    # From the list of field sets, extract a single address per target (to later retrieve the target)
    requested_target_names = {field_set.address.target_name for field_set in request.field_sets}

    # TODO: There is no way this is correct - there must be a simpler way to grab all the swift_sources
    all_targets = await Get(AllTargets, AllTargetsRequest())
    swift_source_targets = [
        target
        for target in all_targets
        if target.has_field(SwiftSourceField)
        and target.address.target_name in requested_target_names
    ]
    sorted_swift_targets = sorted(swift_source_targets, key=lambda x: x.address.target_name)

    # Split up sources into each target/module - and typecheck each independently
    typecheck_results = await MultiGet(
        Get(
            FallibleTypecheckedSwiftModule,
            TypecheckSwiftModuleRequest(target_name, tuple(targets)),
        )
        for target_name, targets in groupby(sorted_swift_targets, lambda x: x.address.target_name)
    )

    return CheckResults(
        [
            CheckResult.from_fallible_process_result(
                typecheck_result.process_result,
                partition_description=f"Typecheck results for {typecheck_result.name}",
            )
            for typecheck_result in typecheck_results
        ],
        checker_name=request.name,
    )


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        UnionRule(CheckRequest, SwiftCheckRequest),
    )
