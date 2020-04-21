# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from abc import ABCMeta
from dataclasses import dataclass

from pants.base.build_root import BuildRoot
from pants.core.util_rules.distdir import DistDir
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoriesToMerge, DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import Configuration, RegisteredTargetTypes, TargetsWithOrigins
from pants.engine.unions import UnionMembership, union


@union
class BinaryConfiguration(Configuration, metaclass=ABCMeta):
    """The fields necessary to create a binary from a target."""


@union
@dataclass(frozen=True)
class CreatedBinary:
    digest: Digest
    binary_name: str


class BinaryOptions(LineOriented, GoalSubsystem):
    """Create a runnable binary."""

    name = "binary"

    required_union_implementations = (BinaryConfiguration,)


class Binary(Goal):
    subsystem_cls = BinaryOptions


@goal_rule
async def create_binary(
    targets_with_origins: TargetsWithOrigins,
    console: Console,
    workspace: Workspace,
    options: BinaryOptions,
    distdir: DistDir,
    buildroot: BuildRoot,
    union_membership: UnionMembership,
    registered_target_types: RegisteredTargetTypes,
) -> Binary:
    targets_to_valid_config_types = BinaryConfiguration.group_targets_to_valid_subclass_config_types(
        targets_with_origins,
        union_membership=union_membership,
        registered_target_types=registered_target_types,
        goal_name=options.name,
        error_if_no_valid_targets=True,
    )
    binaries = await MultiGet(
        Get[CreatedBinary](BinaryConfiguration, valid_config_type.create(target))
        for target, valid_config_types in targets_to_valid_config_types.items()
        for valid_config_type in valid_config_types
    )
    merged_digest = await Get[Digest](
        DirectoriesToMerge(tuple(binary.digest for binary in binaries))
    )
    result = workspace.materialize_directory(
        DirectoryToMaterialize(merged_digest, path_prefix=str(distdir.relpath))
    )
    with options.line_oriented(console) as print_stdout:
        for path in result.output_paths:
            print_stdout(f"Wrote {os.path.relpath(path, buildroot.path)}")
    return Binary(exit_code=0)


def rules():
    return [create_binary]
