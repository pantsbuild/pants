# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import defaultdict
from dataclasses import dataclass
from operator import itemgetter
from typing import (
    ClassVar,
    DefaultDict,
    Generic,
    Iterable,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
    cast,
)

from pants.engine.goal import Goal
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Sources, Target, Targets
from pants.engine.unions import UnionMembership, union
from pants.util.ordered_set import FrozenOrderedSet

_S = TypeVar("_S", bound=Sources)


@union
@dataclass(frozen=True)
class DependenceAnalysisRequest(Generic[_S]):
    """A request to determine what kind of goal data dependence exists for target source fields."""

    source_field_types: ClassVar[Tuple[Type[_S], ...]] = tuple()
    targets: Targets


@dataclass(frozen=True)
class DependenceAnalysisResult:
    goal: Goal
    accesses: Targets
    mutates: Optional[Targets] = None


@dataclass(frozen=True)
class DependenceAnalysis:
    goal_dependence_order: FrozenOrderedSet[Goal]


def update_goal(
    goals_per_target: DefaultDict[Target, List[Goal]], goal: Goal, targets: Targets, append: bool
) -> int:
    """Update goals_per_target for each target, adding goal to the front or back of the list of
    goals.

    Returns the lowest index position for this goal.
    """
    idx = 0
    for target in targets:
        goals = goals_per_target[target]
        if append and goal not in goals:
            idx = max(idx, len(goals))
            goals.append(goal)
        elif not append:
            goals.append(goal)
    return idx


@rule
async def run_dependence_analysis(
    targets: Targets, union_membership: UnionMembership
) -> DependenceAnalysis:
    request_types = cast(
        "Iterable[type[DependenceAnalysisRequest]]", union_membership[DependenceAnalysisRequest]
    )
    requests = [
        request_type(
            Targets(
                tgt
                for tgt in targets
                if any(tgt.has_field(fld) for fld in request_type.source_field_types)
            )
            if request_type.source_field_types
            else targets
        )
        for request_type in request_types
    ]
    results = await MultiGet(
        Get(DependenceAnalysisResult, DependenceAnalysisRequest, request) for request in requests
    )

    # Sort results based on target accesses/mutates data dependence.
    goals_per_target: DefaultDict[Target, List[Goal]] = defaultdict(list)
    goal_orders = sorted(
        [
            (update_goal(goals_per_target, result.goal, result.mutates, append=False), result.goal)
            for result in results
            if result.mutates
        ]
        + [
            (update_goal(goals_per_target, result.goal, result.accesses, append=True), result.goal)
            for result in results
            if result.accesses
        ],
        key=itemgetter(0),
    )

    return DependenceAnalysis(FrozenOrderedSet([goal for _, goal in goal_orders]))


def rules():
    return collect_rules()
