# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

from pants.backend.scala.compile.scalac import CompileScalaSourceRequest, ScalacFieldSet
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.engine.addresses import Addresses
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import CoarsenedTargets, Targets
from pants.engine.unions import UnionRule
from pants.jvm.compile import FallibleCompiledClassfiles
from pants.jvm.resolve.coursier_fetch import CoursierResolveKey
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class ScalacCheckRequest(CheckRequest):
    field_set_type = ScalacFieldSet


@rule(desc="Check compilation for Scala", level=LogLevel.DEBUG)
async def scalac_check(request: ScalacCheckRequest) -> CheckResults:
    coarsened_targets = await Get(
        CoarsenedTargets, Addresses(field_set.address for field_set in request.field_sets)
    )

    resolves = await MultiGet(
        Get(CoursierResolveKey, Targets(t.members)) for t in coarsened_targets
    )

    # TODO: This should be fallible so that we exit cleanly.
    results = await MultiGet(
        Get(FallibleCompiledClassfiles, CompileScalaSourceRequest(component=t, resolve=r))
        for t, r in zip(coarsened_targets, resolves)
    )

    # NB: We return CheckResults with exit codes for the root targets, but we do not pass
    # stdout/stderr because it will already have been rendered as streaming.
    return CheckResults(
        [
            CheckResult(
                result.exit_code,
                stdout="",
                stderr="",
                partition_description=str(coarsened_target),
            )
            for result, coarsened_target in zip(results, coarsened_targets)
        ],
        checker_name="scalac",
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(CheckRequest, ScalacCheckRequest),
    ]
