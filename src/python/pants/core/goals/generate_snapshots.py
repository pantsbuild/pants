# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from abc import ABCMeta
from dataclasses import dataclass

from pants.engine.fs import MergeDigests, Snapshot, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.specs_rules import find_valid_field_sets_for_target_roots
from pants.engine.intrinsics import digest_to_snapshot
from pants.engine.rules import collect_rules, concurrently, goal_rule, implicitly, rule
from pants.engine.target import FieldSet, NoApplicableTargetsBehavior, TargetRootsToFieldSetsRequest
from pants.engine.unions import UnionMembership, union

logger = logging.getLogger(__name__)


@union
class GenerateSnapshotsFieldSet(FieldSet, metaclass=ABCMeta):
    """The fields necessary to generate snapshots from a target."""


@dataclass(frozen=True)
class GenerateSnapshotsResult:
    snapshot: Snapshot


@rule(polymorphic=True)
async def generate_snapshots(field_set: GenerateSnapshotsFieldSet) -> GenerateSnapshotsResult:
    raise NotImplementedError()


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
async def generate_snapshots_goal(workspace: Workspace) -> GenerateSnapshots:
    target_roots_to_field_sets = await find_valid_field_sets_for_target_roots(
        TargetRootsToFieldSetsRequest(
            GenerateSnapshotsFieldSet,
            goal_description=f"the `{GenerateSnapshotsSubsystem.name}` goal",
            no_applicable_targets_behavior=NoApplicableTargetsBehavior.error,
        ),
        **implicitly(),
    )

    if not target_roots_to_field_sets.field_sets:
        return GenerateSnapshots(exit_code=0)

    snapshot_results = await concurrently(
        generate_snapshots(**implicitly({field_set: GenerateSnapshotsFieldSet}))
        for field_set in target_roots_to_field_sets.field_sets
    )

    all_snapshots = await digest_to_snapshot(
        **implicitly(MergeDigests([result.snapshot.digest for result in snapshot_results]))
    )
    workspace.write_digest(all_snapshots.digest)
    for file in all_snapshots.files:
        logger.info(f"Generated {file}")
    return GenerateSnapshots(exit_code=0)


def rules():
    return collect_rules()
