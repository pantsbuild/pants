# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from abc import ABCMeta
from dataclasses import dataclass

from pants.base.build_root import BuildRoot
from pants.core.util_rules.distdir import DistDir
from pants.engine.fs import Digest, DirectoryToMaterialize, MergeDigests, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import FieldSet, TargetsToValidFieldSets, TargetsToValidFieldSetsRequest
from pants.engine.unions import union

# TODO(#6004): use proper Logging singleton, rather than static logger.
logger = logging.getLogger(__name__)


@union
class BinaryFieldSet(FieldSet, metaclass=ABCMeta):
    """The fields necessary to create a binary from a target."""


@dataclass(frozen=True)
class CreatedBinary:
    digest: Digest
    binary_name: str


class BinaryOptions(GoalSubsystem):
    """Create a runnable binary."""

    name = "binary"

    required_union_implementations = (BinaryFieldSet,)


class Binary(Goal):
    subsystem_cls = BinaryOptions


@goal_rule
async def create_binary(workspace: Workspace, dist_dir: DistDir, build_root: BuildRoot) -> Binary:
    targets_to_valid_field_sets = await Get[TargetsToValidFieldSets](
        TargetsToValidFieldSetsRequest(
            BinaryFieldSet, goal_description="the `binary` goal", error_if_no_valid_targets=True
        )
    )
    binaries = await MultiGet(
        Get[CreatedBinary](BinaryFieldSet, field_set)
        for field_set in targets_to_valid_field_sets.field_sets
    )
    merged_digest = await Get[Digest](MergeDigests(binary.digest for binary in binaries))
    result = workspace.materialize_directory(
        DirectoryToMaterialize(merged_digest, path_prefix=str(dist_dir.relpath))
    )
    for path in result.output_paths:
        logger.info(f"Wrote {os.path.relpath(path, build_root.path)}")
    return Binary(exit_code=0)


def rules():
    return [create_binary]
