# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from pants.core.goals.style_request import StyleRequest
from pants.core.util_rules.filter_empty_sources import (
    FieldSetsWithSources,
    FieldSetsWithSourcesRequest,
)
from pants.engine.console import Console
from pants.engine.engine_aware import EngineAwareReturnType
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, QueryRule, _uncacheable_rule, collect_rules, goal_rule
from pants.engine.target import Targets
from pants.engine.unions import UnionMembership, union
from pants.util.logging import LogLevel
from pants.util.memo import memoized_property
from pants.util.meta import frozen_after_init
from pants.util.strutil import strip_v2_chroot_path


@dataclass(frozen=True)
class TypecheckResult:
    exit_code: int
    stdout: str
    stderr: str
    partition_description: Optional[str] = None

    @staticmethod
    def from_fallible_process_result(
        process_result: FallibleProcessResult,
        *,
        partition_description: Optional[str] = None,
        strip_chroot_path: bool = False,
    ) -> "TypecheckResult":
        def prep_output(s: bytes) -> str:
            return strip_v2_chroot_path(s) if strip_chroot_path else s.decode()

        return TypecheckResult(
            exit_code=process_result.exit_code,
            stdout=prep_output(process_result.stdout),
            stderr=prep_output(process_result.stderr),
            partition_description=partition_description,
        )


@frozen_after_init
@dataclass(unsafe_hash=True)
class TypecheckResults:
    """Zero or more TypecheckResult objects for a single type checker.

    Typically, type checkers will return one result. If they no-oped, they will return zero results.
    However, some type checkers may need to partition their input and thus may need to return
    multiple results.
    """

    results: Tuple[TypecheckResult, ...]
    typechecker_name: str

    def __init__(self, results: Iterable[TypecheckResult], *, typechecker_name: str) -> None:
        self.results = tuple(results)
        self.typechecker_name = typechecker_name

    @property
    def skipped(self) -> bool:
        return bool(self.results) is False

    @memoized_property
    def exit_code(self) -> int:
        return next((result.exit_code for result in self.results if result.exit_code != 0), 0)


class EnrichedTypecheckResults(TypecheckResults, EngineAwareReturnType):
    """`TypecheckResults` that are enriched for the sake of logging results as they come in.

    Plugin authors only need to return `TypecheckResults`, and a rule will upcast those into
    `TypecheckResults`.
    """

    def level(self) -> Optional[LogLevel]:
        if self.skipped:
            return LogLevel.DEBUG
        return LogLevel.WARN if self.exit_code != 0 else LogLevel.INFO

    def message(self) -> Optional[str]:
        if self.skipped:
            return f"{self.typechecker_name} skipped."
        message = self.typechecker_name
        message += (
            " succeeded." if self.exit_code == 0 else f" failed (exit code {self.exit_code})."
        )

        def msg_for_result(result: TypecheckResult) -> str:
            msg = ""
            if result.stdout:
                msg += f"\n{result.stdout}"
            if result.stderr:
                msg += f"\n{result.stderr}"
            if msg:
                msg = f"{msg.rstrip()}\n\n"
            return msg

        if len(self.results) == 1:
            results_msg = msg_for_result(self.results[0])
        else:
            results_msg = "\n"
            for i, result in enumerate(self.results):
                msg = f"Partition #{i + 1}"
                msg += (
                    f" - {result.partition_description}:" if result.partition_description else ":"
                )
                msg += msg_for_result(result) or "\n\n"
                results_msg += msg
        message += results_msg
        return message


@union
class TypecheckRequest(StyleRequest):
    """A union for StyleRequests that should be type-checkable.

    Subclass and install a member of this type to provide a linter.
    """


class TypecheckSubsystem(GoalSubsystem):
    """Run type checkers."""

    name = "typecheck"

    required_union_implementations = (TypecheckRequest,)


class Typecheck(Goal):
    subsystem_cls = TypecheckSubsystem


@goal_rule
async def typecheck(
    console: Console, targets: Targets, union_membership: UnionMembership
) -> Typecheck:
    typecheck_request_types = union_membership[TypecheckRequest]
    requests: Iterable[StyleRequest] = tuple(
        lint_request_type(
            lint_request_type.field_set_type.create(target)
            for target in targets
            if lint_request_type.field_set_type.is_applicable(target)
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
    all_results = await MultiGet(
        Get(EnrichedTypecheckResults, TypecheckRequest, request) for request in valid_requests
    )

    exit_code = 0
    if all_results:
        console.print_stderr("")
    for results in sorted(all_results, key=lambda results: results.typechecker_name):
        if results.skipped:
            sigil = console.yellow("-")
            status = "skipped"
        elif results.exit_code == 0:
            sigil = console.green("✓")
            status = "succeeded"
        else:
            sigil = console.red("𐄂")
            status = "failed"
            exit_code = results.exit_code
        console.print_stderr(f"{sigil} {results.typechecker_name} {status}.")

    return Typecheck(exit_code)


# NB: We mark this uncachable to ensure that the results are always streamed, even if the
# underlying TypecheckResults is memoized. This rule is very cheap, so there's little performance
# hit.
@_uncacheable_rule(desc="typecheck")
def enrich_typecheck_results(results: TypecheckResults) -> EnrichedTypecheckResults:
    return EnrichedTypecheckResults(
        results=results.results, typechecker_name=results.typechecker_name
    )


def rules():
    return [
        *collect_rules(),
        # NB: Would be unused otherwise.
        QueryRule(TypecheckSubsystem, []),
    ]
