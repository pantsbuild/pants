# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

from pants.backend.java.compile.javac import CompileJavaSourceRequest, JavacFieldSet
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.engine.addresses import Addresses
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import CoarsenedTargets, Targets
from pants.engine.unions import UnionRule
from pants.jvm.compile import FallibleCompiledClassfiles
from pants.jvm.resolve.coursier_fetch import CoursierResolveKey
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class JavacCheckRequest(CheckRequest):
    field_set_type = JavacFieldSet


@rule(desc="Check javac compilation", level=LogLevel.DEBUG)
async def javac_check(request: JavacCheckRequest) -> CheckResults:
    coarsened_targets = await Get(
        CoarsenedTargets, Addresses(field_set.address for field_set in request.field_sets)
    )

    resolves = await MultiGet(
        Get(CoursierResolveKey, Targets(t.members)) for t in coarsened_targets
    )

    results = await MultiGet(
        Get(
            FallibleCompiledClassfiles,
            CompileJavaSourceRequest(component=target, resolve=resolve),
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
