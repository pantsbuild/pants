# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from abc import ABCMeta
from dataclasses import dataclass

from pants.core.util_rules.environments import EnvironmentNameRequest
from pants.engine.environment import EnvironmentName
from pants.engine.fs import MergeDigests, Snapshot, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import (
    FieldSet,
    NoApplicableTargetsBehavior,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
)
from pants.engine.unions import UnionMembership, union

logger = logging.getLogger(__name__)


@union
class GenerateSnapshotsFieldSet(FieldSet, metaclass=ABCMeta):
    """The fields necessary to generate snapshots from a target."""


@dataclass(frozen=True)
class GenerateSnapshotsResult:
    snapshot: Snapshot


@dataclass(frozen=True)
class EnvironmentAwareGenerateSnapshotsRequest:
    """Request class to request a `GenerateSnapshotsResult` in an environment-aware fashion."""

    field_set: GenerateSnapshotsFieldSet


@rule
async def environment_await_generate_snapshots(
    request: EnvironmentAwareGenerateSnapshotsRequest,
) -> GenerateSnapshotsResult:
    environment_name = await Get(
        EnvironmentName,
        EnvironmentNameRequest,
        EnvironmentNameRequest.from_field_set(request.field_set),
    )
    result = await Get(
        GenerateSnapshotsResult,
        {request.field_set: GenerateSnapshotsFieldSet, environment_name: EnvironmentName},
    )
    return result


class GenerateSnapshotsSubsystem(GoalSubsystem):
    name = "generate-snapshots"
    help = "Generate test snapshots."

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return GenerateSnapshotsFieldSet in union_membership


class GenerateSnapshots(Goal):
    subsystem_cls = GenerateSnapshotsSubsystem
    environment_behavior = Goal.EnvironmentBehavior.USES_ENVIRONMENTS


@goal_rule
async def generate_snapshots(workspace: Workspace) -> GenerateSnapshots:
    target_roots_to_field_sets = await Get(
        TargetRootsToFieldSets,
        TargetRootsToFieldSetsRequest(
            GenerateSnapshotsFieldSet,
            goal_description=f"the `{GenerateSnapshotsSubsystem.name}` goal",
            no_applicable_targets_behavior=NoApplicableTargetsBehavior.error,
        ),
    )

    if not target_roots_to_field_sets.field_sets:
        return GenerateSnapshots(exit_code=0)

    snapshot_results = await MultiGet(
        Get(GenerateSnapshotsResult, EnvironmentAwareGenerateSnapshotsRequest(field_set))
        for field_set in target_roots_to_field_sets.field_sets
    )

    all_snapshots = await Get(
        Snapshot, MergeDigests([result.snapshot.digest for result in snapshot_results])
    )
    workspace.write_digest(all_snapshots.digest)
    for file in all_snapshots.files:
        logger.info(f"Generated {file}")
    return GenerateSnapshots(exit_code=0)


def rules():
    return collect_rules()
