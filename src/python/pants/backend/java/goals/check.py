# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

from pants.backend.java.subsystems.javac import JavacSubsystem
from pants.backend.java.target_types import JavaFieldSet
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.engine.addresses import Addresses
from pants.engine.internals.graph import coarsened_targets as coarsened_targets_get
from pants.engine.rules import Get, collect_rules, concurrently, implicitly, rule
from pants.engine.target import CoarsenedTargets
from pants.engine.unions import UnionRule
from pants.jvm.compile import (
    ClasspathEntryRequest,
    ClasspathEntryRequestFactory,
    FallibleClasspathEntry,
)
from pants.jvm.resolve.coursier_fetch import select_coursier_resolve_for_targets
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class JavacCheckRequest(CheckRequest):
    field_set_type = JavaFieldSet
    tool_name = JavacSubsystem.options_scope


@rule(desc="Check javac compilation", level=LogLevel.DEBUG)
async def javac_check(
    request: JavacCheckRequest,
    classpath_entry_request: ClasspathEntryRequestFactory,
) -> CheckResults:
    coarsened_targets = await coarsened_targets_get(
        **implicitly(Addresses(field_set.address for field_set in request.field_sets))
    )

    # NB: Each root can have an independent resolve, because there is no inherent relation
    # between them other than that they were on the commandline together.
    resolves = await concurrently(
        select_coursier_resolve_for_targets(CoarsenedTargets([t]), **implicitly())
        for t in coarsened_targets
    )

    results = await concurrently(
        Get(
            FallibleClasspathEntry,
            ClasspathEntryRequest,
            classpath_entry_request.for_targets(component=target, resolve=resolve),
        )
        for target, resolve in zip(coarsened_targets, resolves)
    )

    # NB: We don't pass stdout/stderr as it will have already been rendered as streaming.
    exit_code = next((result.exit_code for result in results if result.exit_code != 0), 0)
    return CheckResults([CheckResult(exit_code, "", "")], checker_name=request.tool_name)


def rules():
    return [
        *collect_rules(),
        UnionRule(CheckRequest, JavacCheckRequest),
    ]
