# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import cast

from pants.backend.go.target_types import GoFirstPartyPackageSourcesField
from pants.backend.go.util_rules.build_pkg import (
    BuildGoPackageRequest,
    BuildGoPackageTargetRequest,
    FallibleBuildGoPackageRequest,
    FallibleBuiltGoPackage,
)
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet
from pants.engine.unions import UnionRule


@dataclass(frozen=True)
class GoCheckFieldSet(FieldSet):
    required_fields = (GoFirstPartyPackageSourcesField,)

    sources: GoFirstPartyPackageSourcesField


class GoCheckRequest(CheckRequest):
    field_set_type = GoCheckFieldSet


@rule
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

    # TODO: Update `build_pkg.py` to use streaming workunits to log compilation results, which has
    #  the benefit of other contexts like `test.py` using it. Switch this to only preserve the
    #  exit code.
    check_results = [
        *(
            CheckResult(
                result.exit_code,
                "",
                cast(str, result.stderr),
                partition_description=result.import_path,
            )
            for result in invalid_requests
        ),
        *(
            CheckResult(
                result.exit_code,
                result.stdout or "",
                result.stderr or "",
                partition_description=result.import_path,
            )
            for result in build_results
        ),
    ]
    return CheckResults(check_results, checker_name="go")


def rules():
    return [*collect_rules(), UnionRule(CheckRequest, GoCheckRequest)]
