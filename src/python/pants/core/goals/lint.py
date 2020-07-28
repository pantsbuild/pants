# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable, Optional, cast

from pants.core.goals.style_request import StyleRequest
from pants.core.util_rules.filter_empty_sources import (
    FieldSetsWithSources,
    FieldSetsWithSourcesRequest,
)
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.fs import Digest, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import TargetsWithOrigins
from pants.engine.unions import UnionMembership, union
from pants.util.strutil import strip_v2_chroot_path


@dataclass(frozen=True)
class LintResultFile:
    output_path: PurePath
    digest: Digest


@dataclass(frozen=True)
class LintResult:
    exit_code: int
    stdout: str
    stderr: str
    linter_name: str
    results_file: Optional[LintResultFile]

    @staticmethod
    def from_fallible_process_result(
        process_result: FallibleProcessResult,
        *,
        linter_name: str,
        strip_chroot_path: bool = False,
        results_file: Optional[LintResultFile] = None,
    ) -> "LintResult":
        def prep_output(s: bytes) -> str:
            return strip_v2_chroot_path(s) if strip_chroot_path else s.decode()

        return LintResult(
            exit_code=process_result.exit_code,
            stdout=prep_output(process_result.stdout),
            stderr=prep_output(process_result.stderr),
            linter_name=linter_name,
            results_file=results_file,
        )

    def materialize(self, console: Console, workspace: Workspace) -> None:
        if not self.results_file:
            return
        output_path = self.results_file.output_path
        workspace.write_digest(self.results_file.digest, path_prefix=output_path.parent.as_posix())
        console.print_stdout(f"Wrote {self.linter_name} report to: {output_path.as_posix()}")


class LintResults(Collection[LintResult]):
    """Zero or more LintResult objects for a single linter.

    Typically, linters will return one result. If they no-oped, they will return zero results.
    However, some linters may need to partition their input and thus may need to return multiple
    results. For example, many Python linters will need to group by interpreter compatibility.
    """


@union
class LintRequest(StyleRequest):
    """A union for StyleRequests that should be lintable.

    Subclass and install a member of this type to provide a linter.
    """


class LintSubsystem(GoalSubsystem):
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
        register(
            "--reports-dir",
            type=str,
            metavar="<DIR>",
            default=None,
            advanced=True,
            help="Specifying a directory causes linter that support it to write report files into this directory",
        )

    @property
    def per_target_caching(self) -> bool:
        return cast(bool, self.options.per_target_caching)

    @property
    def reports_dir(self) -> Optional[PurePath]:
        v = self.options.reports_dir
        return PurePath(v) if v else None


class Lint(Goal):
    subsystem_cls = LintSubsystem


@goal_rule
async def lint(
    console: Console,
    workspace: Workspace,
    targets_with_origins: TargetsWithOrigins,
    lint_subsystem: LintSubsystem,
    union_membership: UnionMembership,
) -> Lint:
    request_types = union_membership[LintRequest]
    requests: Iterable[StyleRequest] = tuple(
        request_type(
            request_type.field_set_type.create(target_with_origin)
            for target_with_origin in targets_with_origins
            if request_type.field_set_type.is_valid(target_with_origin.target)
        )
        for request_type in request_types
    )
    field_sets_with_sources: Iterable[FieldSetsWithSources] = await MultiGet(
        Get(FieldSetsWithSources, FieldSetsWithSourcesRequest(request.field_sets))
        for request in requests
    )
    valid_requests: Iterable[StyleRequest] = tuple(
        request_cls(request)
        for request_cls, request in zip(request_types, field_sets_with_sources)
        if request
    )

    if lint_subsystem.per_target_caching:
        results = await MultiGet(
            Get(LintResults, LintRequest, request.__class__([field_set]))
            for request in valid_requests
            for field_set in request.field_sets
        )
    else:
        results = await MultiGet(
            Get(LintResults, LintRequest, lint_request) for lint_request in valid_requests
        )

    sorted_results = sorted(itertools.chain.from_iterable(results), key=lambda res: res.linter_name)
    if not sorted_results:
        return Lint(exit_code=0)

    exit_code = 0
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
        result.materialize(console, workspace)
        if result.exit_code != 0:
            exit_code = result.exit_code

    return Lint(exit_code)


def rules():
    return collect_rules()
