# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from dataclasses import dataclass
from typing import Iterable

from pants.core.goals.style_request import StyleRequest
from pants.core.util_rules.filter_empty_sources import (
    FieldSetsWithSources,
    FieldSetsWithSourcesRequest,
)
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import TargetsWithOrigins
from pants.engine.unions import UnionMembership, union
from pants.util.strutil import strip_v2_chroot_path


@dataclass(frozen=True)
class TypecheckResult:
    exit_code: int
    stdout: str
    stderr: str
    typechecker_name: str

    @staticmethod
    def from_fallible_process_result(
        process_result: FallibleProcessResult,
        *,
        typechecker_name: str,
        strip_chroot_path: bool = False,
    ) -> "TypecheckResult":
        def prep_output(s: bytes) -> str:
            return strip_v2_chroot_path(s) if strip_chroot_path else s.decode()

        return TypecheckResult(
            exit_code=process_result.exit_code,
            stdout=prep_output(process_result.stdout),
            stderr=prep_output(process_result.stderr),
            typechecker_name=typechecker_name,
        )


class TypecheckResults(Collection[TypecheckResult]):
    """Zero or more TypecheckResult objects for a single type checker.

    Typically, type checkers will return one result. If they no-oped, they will return zero results.
    However, some type checkers may need to partition their input and thus may need to return
    multiple results.
    """


@union
class TypecheckRequest(StyleRequest):
    """A union for StyleRequests that should be type-checkable.

    Subclass and install a member of this type to provide a linter.
    """


class TypecheckOptions(GoalSubsystem):
    """Run type checkers."""

    name = "typecheck"

    required_union_implementations = (TypecheckRequest,)


class Typecheck(Goal):
    subsystem_cls = TypecheckOptions


@goal_rule
async def typecheck(
    console: Console, targets_with_origins: TargetsWithOrigins, union_membership: UnionMembership
) -> Typecheck:
    typecheck_request_types = union_membership[TypecheckRequest]
    requests: Iterable[StyleRequest] = tuple(
        lint_request_type(
            lint_request_type.field_set_type.create(target_with_origin)
            for target_with_origin in targets_with_origins
            if lint_request_type.field_set_type.is_valid(target_with_origin.target)
        )
        for lint_request_type in typecheck_request_types
    )
    field_sets_with_sources: Iterable[FieldSetsWithSources] = await MultiGet(
        Get(FieldSetsWithSources, FieldSetsWithSourcesRequest(request.field_sets))
        for request in requests
    )
    valid_requests: Iterable[StyleRequest] = tuple(
        request_cls(request)
        for request_cls, request in zip(typecheck_request_types, field_sets_with_sources)
        if request
    )
    results = await MultiGet(
        Get(TypecheckResults, TypecheckRequest, request) for request in valid_requests
    )

    sorted_results = sorted(
        itertools.chain.from_iterable(results), key=lambda res: res.typechecker_name
    )
    if not sorted_results:
        return Typecheck(exit_code=0)

    exit_code = 0
    for result in sorted_results:
        console.print_stderr(
            f"{console.green('✓')} {result.typechecker_name} succeeded."
            if result.exit_code == 0
            else f"{console.red('𐄂')} {result.typechecker_name} failed."
        )
        if result.stdout:
            console.print_stderr(result.stdout)
        if result.stderr:
            console.print_stderr(result.stderr)
        if result != sorted_results[-1]:
            console.print_stderr("")
        if result.exit_code != 0:
            exit_code = result.exit_code

    return Typecheck(exit_code)


def rules():
    return [typecheck]
