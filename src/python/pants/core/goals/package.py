# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from abc import ABCMeta
from dataclasses import dataclass
from typing import Optional

from pants.core.util_rules.distdir import DistDir
from pants.engine.fs import Digest, MergeDigests, Snapshot, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import FieldSet, TargetRootsToFieldSets, TargetRootsToFieldSetsRequest
from pants.engine.unions import union

logger = logging.getLogger(__name__)


@union
class PackageFieldSet(FieldSet, metaclass=ABCMeta):
    """The fields necessary to build an asset from a target."""


@dataclass(frozen=True)
class BuiltPackage:
    digest: Digest
    relpath: str
    extra_log_info: Optional[str] = None


class PackageSubsystem(GoalSubsystem):
    """Create a distributable package."""

    name = "package"

    required_union_implementations = (PackageFieldSet,)


class Package(Goal):
    subsystem_cls = PackageSubsystem


@goal_rule
async def package_asset(workspace: Workspace, dist_dir: DistDir) -> Package:
    target_roots_to_field_sets = await Get(
        TargetRootsToFieldSets,
        TargetRootsToFieldSetsRequest(
            PackageFieldSet,
            goal_description="the `package` goal",
            error_if_no_applicable_targets=True,
        ),
    )
    assets = await MultiGet(
        Get(BuiltPackage, PackageFieldSet, field_set)
        for field_set in target_roots_to_field_sets.field_sets
    )
    merged_snapshot = await Get(Snapshot, MergeDigests(asset.digest for asset in assets))
    workspace.write_digest(merged_snapshot.digest, path_prefix=str(dist_dir.relpath))
    for asset in assets:
        msg = f"Wrote {dist_dir.relpath / asset.relpath}"
        if asset.extra_log_info:
            msg += f"\n{asset.extra_log_info}"
        logger.info(msg)
    return Package(exit_code=0)


def rules():
    return collect_rules()
