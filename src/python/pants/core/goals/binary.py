# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from abc import ABCMeta
from dataclasses import dataclass

from pants.core.util_rules.distdir import DistDir
from pants.engine.fs import Digest, MergeDigests, Snapshot, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import FieldSet, TargetRootsToFieldSets, TargetRootsToFieldSetsRequest
from pants.engine.unions import union

logger = logging.getLogger(__name__)


@union
class BinaryFieldSet(FieldSet, metaclass=ABCMeta):
    """The fields necessary to create a binary from a target."""


@dataclass(frozen=True)
class CreatedBinary:
    digest: Digest
    binary_name: str


class BinarySubsystem(GoalSubsystem):
    """Deprecated in favor of the `package` goal."""

    name = "binary"

    required_union_implementations = (BinaryFieldSet,)


class Binary(Goal):
    subsystem_cls = BinarySubsystem


@goal_rule
async def create_binary(workspace: Workspace, dist_dir: DistDir) -> Binary:
    logger.warning(
        "The `binary` goal is deprecated in favor of the `package` goal, which behaves "
        "identically. `binary` will be removed in 2.1.0.dev0.",
    )
    target_roots_to_field_sets = await Get(
        TargetRootsToFieldSets,
        TargetRootsToFieldSetsRequest(
            BinaryFieldSet,
            goal_description="the `binary` goal",
            error_if_no_applicable_targets=True,
        ),
    )
    binaries = await MultiGet(
        Get(CreatedBinary, BinaryFieldSet, field_set)
        for field_set in target_roots_to_field_sets.field_sets
    )
    merged_snapshot = await Get(Snapshot, MergeDigests(binary.digest for binary in binaries))
    workspace.write_digest(merged_snapshot.digest, path_prefix=str(dist_dir.relpath))
    for path in merged_snapshot.files:
        logger.info(f"Wrote {dist_dir.relpath / path}")
    return Binary(exit_code=0)


def rules():
    return collect_rules()
