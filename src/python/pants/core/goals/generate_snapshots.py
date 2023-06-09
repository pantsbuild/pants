# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABCMeta
from dataclasses import dataclass
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import collect_rules, goal_rule, Get, MultiGet
from pants.engine.target import FieldSet, NoApplicableTargetsBehavior, TargetRootsToFieldSets, TargetRootsToFieldSetsRequest
from pants.engine.unions import UnionMembership, union
from pants.engine.fs import Digest, Workspace, MergeDigests, Snapshot


@union
class GenerateSnapshotsFieldSet(FieldSet, metaclass=ABCMeta):
    pass

@dataclass(frozen=True)
class GenerateSnapshotsResult:
    snapshot: Snapshot

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
            no_applicable_targets_behavior=NoApplicableTargetsBehavior.warn,
        ),
    )
    if not target_roots_to_field_sets.field_sets:
        return GenerateSnapshots(exit_code=0)

    snapshot_results = await MultiGet(
        Get(GenerateSnapshotsResult, GenerateSnapshotsFieldSet, field_set)
        for field_set in target_roots_to_field_sets.field_sets
    )

    all_snapshots = await Get(Digest, MergeDigests([result.snapshot.digest for result in snapshot_results]))
    workspace.write_digest(all_snapshots)
    return GenerateSnapshots(exit_code=0)

def rules():
    return collect_rules()
