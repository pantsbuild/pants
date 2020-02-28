# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import List

from pants.backend.python.lint.python_lint_target import PYTHON_TARGET_TYPES
from pants.engine.fs import Digest, Snapshot
from pants.engine.legacy.structs import (
    PantsPluginAdaptorWithOrigin,
    PythonAppAdaptorWithOrigin,
    PythonBinaryAdaptorWithOrigin,
    PythonTargetAdaptorWithOrigin,
    PythonTestsAdaptorWithOrigin,
    TargetAdaptorWithOrigin,
)
from pants.engine.objects import union
from pants.engine.rules import RootRule, UnionMembership, UnionRule, rule
from pants.engine.selectors import Get
from pants.rules.core.fmt import AggregatedFmtResults, FmtResult, FormatTarget


@union
@dataclass(frozen=True)
class PythonFormatTarget:
    adaptor_with_origin: TargetAdaptorWithOrigin


@rule
async def format_python_target(
    target: PythonFormatTarget, union_membership: UnionMembership
) -> AggregatedFmtResults:
    """This aggregator allows us to have multiple formatters safely operate over the same Python
    targets, even if they modify the same files."""
    adaptor_with_origin = target.adaptor_with_origin
    prior_formatter_result = adaptor_with_origin.adaptor.sources.snapshot
    results: List[FmtResult] = []
    for member in union_membership.union_rules[PythonFormatTarget]:
        result = await Get[FmtResult](
            PythonFormatTarget,
            member((adaptor_with_origin,), prior_formatter_result=prior_formatter_result),
        )
        results.append(result)
        if result != FmtResult.noop():
            prior_formatter_result = await Get[Snapshot](Digest, result.digest)
    return AggregatedFmtResults(
        tuple(results), combined_digest=prior_formatter_result.directory_digest
    )


@rule
def target_adaptor(adaptor_with_origin: PythonTargetAdaptorWithOrigin) -> PythonFormatTarget:
    return PythonFormatTarget(adaptor_with_origin)


@rule
def app_adaptor(adaptor_with_origin: PythonAppAdaptorWithOrigin) -> PythonFormatTarget:
    return PythonFormatTarget(adaptor_with_origin)


@rule
def binary_adaptor(adaptor_with_origin: PythonBinaryAdaptorWithOrigin) -> PythonFormatTarget:
    return PythonFormatTarget(adaptor_with_origin)


@rule
def tests_adaptor(adaptor_with_origin: PythonTestsAdaptorWithOrigin) -> PythonFormatTarget:
    return PythonFormatTarget(adaptor_with_origin)


@rule
def plugin_adaptor(adaptor_with_origin: PantsPluginAdaptorWithOrigin) -> PythonFormatTarget:
    return PythonFormatTarget(adaptor_with_origin)


def rules():
    return [
        format_python_target,
        target_adaptor,
        app_adaptor,
        binary_adaptor,
        tests_adaptor,
        plugin_adaptor,
        *(RootRule(target_type) for target_type in PYTHON_TARGET_TYPES),
        *(UnionRule(FormatTarget, target_type) for target_type in PYTHON_TARGET_TYPES),
    ]
