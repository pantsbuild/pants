# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

from pants.backend.java.target_types import JavaFieldSet
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.engine.addresses import Addresses
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import CoarsenedTargets, Targets
from pants.engine.unions import UnionMembership, UnionRule
from pants.jvm.compile import ClasspathEntryRequest, FallibleClasspathEntry
from pants.jvm.resolve.key import CoursierResolveKey
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class JavacCheckRequest(CheckRequest):
    field_set_type = JavaFieldSet


@rule(desc="Check javac compilation", level=LogLevel.DEBUG)
async def javac_check(
    request: JavacCheckRequest,
    union_membership: UnionMembership,
) -> CheckResults:
    coarsened_targets = await Get(
        CoarsenedTargets, Addresses(field_set.address for field_set in request.field_sets)
    )

    resolves = await MultiGet(
        Get(CoursierResolveKey, Targets(t.members)) for t in coarsened_targets
    )

    results = await MultiGet(
        Get(
            FallibleClasspathEntry,
            ClasspathEntryRequest,
            ClasspathEntryRequest.for_targets(union_membership, component=target, resolve=resolve),
        )
        for target, resolve in zip(coarsened_targets, resolves)
    )

    # NB: We don't pass stdout/stderr as it will have already been rendered as streaming.
    exit_code = next((result.exit_code for result in results if result.exit_code != 0), 0)
    return CheckResults([CheckResult(exit_code, "", "")], checker_name="javac")


def rules():
    return [
        *collect_rules(),
        UnionRule(CheckRequest, JavacCheckRequest),
    ]
