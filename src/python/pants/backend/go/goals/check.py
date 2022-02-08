# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.go.target_types import GoPackageSourcesField
from pants.backend.go.util_rules.build_pkg import (
    BuildGoPackageRequest,
    FallibleBuildGoPackageRequest,
    FallibleBuiltGoPackage,
)
from pants.backend.go.util_rules.build_pkg_target import BuildGoPackageTargetRequest
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class GoCheckFieldSet(FieldSet):
    required_fields = (GoPackageSourcesField,)


class GoCheckRequest(CheckRequest):
    field_set_type = GoCheckFieldSet
    name = "go-compile"


@rule(desc="Check Go compilation", level=LogLevel.DEBUG)
async def check_go(request: GoCheckRequest) -> CheckResults:
    build_requests = await MultiGet(
        Get(FallibleBuildGoPackageRequest, BuildGoPackageTargetRequest(field_set.address))
        for field_set in request.field_sets
    )
    invalid_requests = []
    valid_requests = []
    for fallible_request in build_requests:
        if fallible_request.request is None:
            invalid_requests.append(fallible_request)
        else:
            valid_requests.append(fallible_request.request)

    build_results = await MultiGet(
        Get(FallibleBuiltGoPackage, BuildGoPackageRequest, request) for request in valid_requests
    )

    # NB: We don't pass stdout/stderr as it will have already been rendered as streaming.
    exit_code = next(
        (
            result.exit_code  # type: ignore[attr-defined]
            for result in (*build_results, *invalid_requests)
            if result.exit_code != 0  # type: ignore[attr-defined]
        ),
        0,
    )
    return CheckResults([CheckResult(exit_code, "", "")], checker_name=request.name)


def rules():
    return [*collect_rules(), UnionRule(CheckRequest, GoCheckRequest)]
