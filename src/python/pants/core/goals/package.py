# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from abc import ABCMeta
from dataclasses import dataclass
from typing import Optional, Tuple

from pants.core.util_rules.distdir import DistDir
from pants.engine.addresses import Address
from pants.engine.fs import Digest, MergeDigests, Snapshot, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import (
    FieldSet,
    StringField,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
)
from pants.engine.unions import union

logger = logging.getLogger(__name__)


@union
class PackageFieldSet(FieldSet, metaclass=ABCMeta):
    """The fields necessary to build an asset from a target."""


@dataclass(frozen=True)
class BuiltPackageArtifact:
    """Information about artifacts in a built package.

    Used for logging information about the artifacts that are dumped to the distdir.
    """

    relpath: Optional[str]
    extra_log_lines: Tuple[str, ...] = tuple()


@dataclass(frozen=True)
class BuiltPackage:
    digest: Digest
    artifacts: Tuple[BuiltPackageArtifact, ...]


class OutputPathField(StringField):
    """Where the built asset should be located.

    If undefined, this will use the path to the the BUILD, followed by the target name. For
    example, `src/python/project:app` would be `src.python.project/app.ext`.

    When running `./pants package`, this path will be prefixed by `--distdir` (e.g. `dist/`).

    Warning: setting this value risks naming collisions with other package targets you may have.
    """

    alias = "output_path"

    def value_or_default(
        self, address: Address, *, file_ending: str, use_legacy_format: bool
    ) -> str:
        assert not file_ending.startswith("."), "`file_ending` should not start with `.`"
        if self.value is not None:
            return self.value
        if use_legacy_format:
            return f"{address.target_name}.{file_ending}"
        return os.path.join(
            address.spec_path.replace(os.sep, "."), f"{address.target_name}.{file_ending}"
        )


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
            error_if_no_applicable_targets=False,
        ),
    )
    if not target_roots_to_field_sets.field_sets:
        return Package(exit_code=0)

    packages = await MultiGet(
        Get(BuiltPackage, PackageFieldSet, field_set)
        for field_set in target_roots_to_field_sets.field_sets
    )
    merged_snapshot = await Get(Snapshot, MergeDigests(pkg.digest for pkg in packages))
    workspace.write_digest(merged_snapshot.digest, path_prefix=str(dist_dir.relpath))
    for pkg in packages:
        for artifact in pkg.artifacts:
            msg = ""
            if artifact.relpath:
                msg += f"Wrote {dist_dir.relpath / artifact.relpath}"
            for line in artifact.extra_log_lines:
                msg += f"\n{line}"
            logger.info(msg)
    return Package(exit_code=0)


def rules():
    return collect_rules()
