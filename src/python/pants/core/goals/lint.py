# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
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
class LintResult:
    exit_code: int
    stdout: str
    stderr: str
    linter_name: str

    @staticmethod
    def from_fallible_process_result(
        process_result: FallibleProcessResult, *, linter_name: str, strip_chroot_path: bool = False
    ) -> "LintResult":
        def prep_output(s: bytes) -> str:
            return strip_v2_chroot_path(s) if strip_chroot_path else s.decode()

        return LintResult(
            exit_code=process_result.exit_code,
            stdout=prep_output(process_result.stdout),
            stderr=prep_output(process_result.stderr),
            linter_name=linter_name,
        )


class LintResults(Collection[LintResult]):
    """Zero or more LintResult objects for a single linter.

    Typically, linters will return one result. If they no-oped, they will return zero results.
    However, some linters may need to partition their batch of LinterFieldSets and thus may need to
    return multiple results. For example, many Python linters will need to group by interpreter
    compatibility.
    """


@union
class LintRequest(StyleRequest):
    """A union for StyleRequests that should be lintable.

    Subclass and install a member of this type to provide a linter.
    """


class LintOptions(GoalSubsystem):
    """Lint source code."""

    name = "lint"

    required_union_implementations = (LintRequest,)

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--per-target-caching",
            advanced=True,
            type=bool,
            default=False,
            help=(
                "Rather than running all targets in a single batch, run each target as a "
                "separate process. Why do this? You'll get many more cache hits. Why not do this? "
                "Linters both have substantial startup overhead and are cheap to add one "
                "additional file to the run. On a cold cache, it is much faster to use "
                "`--no-per-target-caching`. We only recommend using `--per-target-caching` if you "
                "are using a remote cache or if you have benchmarked that this option will be "
                "faster than `--no-per-target-caching` for your use case."
            ),
        )


class Lint(Goal):
    subsystem_cls = LintOptions


@goal_rule
async def lint(
    console: Console,
    targets_with_origins: TargetsWithOrigins,
    options: LintOptions,
    union_membership: UnionMembership,
) -> Lint:
    lint_request_types = union_membership[LintRequest]
    lint_requests: Iterable[StyleRequest] = tuple(
        lint_request_type(
            lint_request_type.field_set_type.create(target_with_origin)
            for target_with_origin in targets_with_origins
            if lint_request_type.field_set_type.is_valid(target_with_origin.target)
        )
        for lint_request_type in union_membership[LintRequest]
    )
    field_sets_with_sources: Iterable[FieldSetsWithSources] = await MultiGet(
        Get[FieldSetsWithSources](FieldSetsWithSourcesRequest(lint_request.field_sets))
        for lint_request in lint_requests
    )
    valid_lint_requests: Iterable[StyleRequest] = tuple(
        lint_request_cls(lint_request)
        for lint_request_cls, lint_request in zip(lint_request_types, field_sets_with_sources)
        if lint_request
    )

    if options.values.per_target_caching:
        results = await MultiGet(
            Get[LintResults](LintRequest, lint_request.__class__([field_set]))
            for lint_request in valid_lint_requests
            for field_set in lint_request.field_sets
        )
    else:
        results = await MultiGet(
            Get[LintResults](LintRequest, lint_request) for lint_request in valid_lint_requests
        )

    if not results:
        return Lint(exit_code=0)

    exit_code = 0
    sorted_results = sorted(itertools.chain.from_iterable(results), key=lambda res: res.linter_name)
    for result in sorted_results:
        console.print_stderr(
            f"{console.green('✓')} {result.linter_name} succeeded."
            if result.exit_code == 0
            else f"{console.red('𐄂')} {result.linter_name} failed."
        )
        if result.stdout:
            console.print_stderr(result.stdout)
        if result.stderr:
            console.print_stderr(result.stderr)
        if result != sorted_results[-1]:
            console.print_stderr("")
        if result.exit_code != 0:
            exit_code = result.exit_code

    return Lint(exit_code)


def rules():
    return [lint]
