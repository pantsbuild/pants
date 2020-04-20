# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import os
from abc import ABCMeta
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Sequence, Type

from pants.base.build_root import BuildRoot
from pants.core.util_rules.distdir import DistDir
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoriesToMerge, DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import Configuration, RegisteredTargetTypes, Target, TargetsWithOrigins
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


def gather_valid_binary_configuration_types(
    goal_subsytem: GoalSubsystem,
    targets_with_origins: TargetsWithOrigins,
    union_membership: UnionMembership,
    registered_target_types: RegisteredTargetTypes,
) -> Mapping[Target, Sequence[Type[BinaryConfiguration]]]:
    config_types: Iterable[Type[BinaryConfiguration]] = union_membership.union_rules[
        BinaryConfiguration
    ]
    valid_config_types_by_target: Dict[Target, List[Type[BinaryConfiguration]]] = {}
    valid_target_aliases = set()
    for target_with_origin in targets_with_origins:
        for config_type in config_types:
            if config_type.is_valid(target_with_origin.target):
                valid_config_types_by_target.setdefault(target_with_origin.target, []).append(
                    config_type
                )
                valid_target_aliases.add(target_with_origin.target.alias)

    if not valid_config_types_by_target:
        all_valid_target_types = itertools.chain.from_iterable(
            config_type.valid_target_types(
                registered_target_types.types, union_membership=union_membership
            )
            for config_type in config_types
        )
        all_valid_target_aliases = sorted(
            target_type.alias for target_type in all_valid_target_types
        )
        invalid_target_aliases = sorted(
            {
                target_with_origin.target.alias
                for target_with_origin in targets_with_origins
                if target_with_origin.target.alias not in valid_target_aliases
            }
        )
        specs = sorted(
            {
                target_with_origin.origin.to_spec_string()
                for target_with_origin in targets_with_origins
            }
        )
        bulleted_list_sep = "\n  * "
        raise ValueError(
            f"The `{goal_subsytem.name}` goal only works with the following target types:"
            f"{bulleted_list_sep}{bulleted_list_sep.join(all_valid_target_aliases)}\n\n"
            f"You specified `{' '.join(specs)}` which only included the following target types:"
            f"{bulleted_list_sep}{bulleted_list_sep.join(invalid_target_aliases)}"
        )
    return valid_config_types_by_target


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
    valid_config_types_by_target = gather_valid_binary_configuration_types(
        goal_subsytem=options,
        targets_with_origins=targets_with_origins,
        union_membership=union_membership,
        registered_target_types=registered_target_types,
    )
    binaries = await MultiGet(
        Get[CreatedBinary](BinaryConfiguration, valid_config_type.create(target))
        for target, valid_config_types in valid_config_types_by_target.items()
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
