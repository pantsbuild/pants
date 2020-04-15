# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
import itertools
import os
from abc import ABC
from dataclasses import dataclass
from typing import ClassVar, Dict, Iterable, List, Mapping, Sequence, Tuple, Type

from pants.base.build_root import BuildRoot
from pants.build_graph.address import Address
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoriesToMerge, DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.objects import union
from pants.engine.rules import UnionMembership, goal_rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import Field, RegisteredTargetTypes, Target, TargetsWithOrigins
from pants.rules.core.distdir import DistDir


# TODO: Factor this out once porting fmt.py and lint.py to the Target API.
@union
@dataclass(frozen=True)
class BinaryConfiguration(ABC):
    """An ad hoc collection of the fields necessary to create a binary from a target."""

    required_fields: ClassVar[Tuple[Type[Field], ...]]

    address: Address

    @classmethod
    def is_valid(cls, tgt: Target) -> bool:
        return tgt.has_fields(cls.required_fields)

    @classmethod
    def valid_target_types(
        cls, target_types: Iterable[Type[Target]], *, union_membership: UnionMembership
    ) -> Tuple[Type[Target], ...]:
        return tuple(
            target_type
            for target_type in target_types
            if target_type.class_has_fields(cls.required_fields, union_membership=union_membership)
        )

    # TODO: this won't handle any non-Field attributes defined on the configuration. It also
    # doesn't allow us to override the `default_raw_value` (do we really care about this?).
    @classmethod
    def create(cls, tgt: Target) -> "BinaryConfiguration":
        all_expected_fields: Dict[str, Type[Field]] = {
            dataclass_field.name: dataclass_field.type
            for dataclass_field in dataclasses.fields(cls)
            if isinstance(dataclass_field.type, type) and issubclass(dataclass_field.type, Field)  # type: ignore[unreachable]
        }
        return cls(  # type: ignore[call-arg]
            address=tgt.address,
            **{
                dataclass_field_name: (
                    tgt[field_cls] if field_cls in cls.required_fields else tgt.get(field_cls)
                )
                for dataclass_field_name, field_cls in all_expected_fields.items()
            },
        )


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
