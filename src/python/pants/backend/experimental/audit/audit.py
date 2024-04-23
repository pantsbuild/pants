# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, ClassVar, Generic, Iterable, TypeVar

from pants.core.goals.lint import REPORT_DIR as REPORT_DIR  # noqa: F401
from pants.core.goals.multi_tool_goal_helper import determine_specified_tool_ids
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, goal_rule
from pants.engine.target import FieldSet, FilteredTargets
from pants.engine.unions import UnionMembership, union

logger = logging.getLogger(__name__)
_FS = TypeVar("_FS", bound=FieldSet)


@dataclass(frozen=True)
class AuditResult:
    resolve_name: str
    lockfile: str
    report: str


@dataclass(unsafe_hash=True)
class AuditResults(EngineAwareReturnType):
    """Zero or more AuditResult objects for a single auditor."""

    results: tuple[AuditResult, ...]
    auditor_name: str

    def __init__(self, results: Iterable[AuditResult], *, auditor_name: str) -> None:
        self.results = tuple(results)
        self.auditor_name = auditor_name

    def cacheable(self) -> bool:
        """Is marked uncacheable to ensure that it always renders."""
        return False


@union
@dataclass(unsafe_hash=True)
class AuditRequest(Generic[_FS], EngineAwareParameter):
    """A union for targets that should be audited.

    Subclass and install a member of this type to provide an auditor.
    """

    field_set_type: ClassVar[type[_FS]]  # type: ignore[misc]
    tool_id: ClassVar[str]

    field_sets: Collection[_FS]

    def __init__(self, field_sets: Iterable[_FS]) -> None:
        self.field_sets = Collection[_FS](field_sets)

    def debug_hint(self) -> str:
        return self.tool_id

    def metadata(self) -> dict[str, Any]:
        return {"addresses": [fs.address.spec for fs in self.field_sets]}


class AuditSubsystem(GoalSubsystem):
    name = "audit"
    help = "Run third party dependency audit tools."

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return AuditRequest in union_membership


class Audit(Goal):
    subsystem_cls = AuditSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY


@goal_rule
async def audit(
    console: Console,
    targets: FilteredTargets,
    union_membership: UnionMembership,
) -> Audit:
    request_types = union_membership[AuditRequest]
    specified_ids = determine_specified_tool_ids(
        "audit",
        [
            "pypi-audit",
        ],
        request_types,
    )
    requests = tuple(
        request_type(
            request_type.field_set_type.create(target)
            for target in targets
            if (
                request_type.tool_id in specified_ids
                and request_type.field_set_type.is_applicable(target)
            )
        )
        for request_type in request_types
    )

    all_results = await MultiGet(Get(AuditResults, {request: AuditRequest}) for request in requests)
    for results in all_results:
        for result in results.results:
            if result.report:
                sigil = console.sigil_failed()
            else:
                sigil = console.sigil_succeeded()
            console.print_stdout(
                f"\n\n{sigil} Resolve: {result.resolve_name} (from {result.lockfile})"
            )
            if result.report:
                console.print_stdout(result.report)
            else:
                console.print_stdout("No vulnerabilities reported.")

    return Audit(0)


def rules():
    return [
        *collect_rules(),
    ]
