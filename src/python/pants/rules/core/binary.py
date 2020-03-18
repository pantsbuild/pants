# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, Iterable, Tuple, Type

from pants.build_graph.address import Address
from pants.engine.addressable import Addresses
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoriesToMerge, DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.objects import union
from pants.engine.rules import UnionMembership, goal_rule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import Field, RegisteredTargetTypes, Target, WrappedTarget
from pants.rules.core.distdir import DistDir


# TODO: This might not be the right level of abstraction. Possibly factor out some superclass.
#  Revisit after porting lint.py, fmt.py, and test.py to use the Target API.
@union
class BinaryImplementation(ABC):
    required_fields: ClassVar[Tuple[Type[Field], ...]]

    @classmethod
    def is_valid_target(cls, tgt: Target) -> bool:
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

    @classmethod
    @abstractmethod
    def create(cls, tgt: Target) -> "BinaryImplementation":
        pass


@union
@dataclass(frozen=True)
class CreatedBinary:
    digest: Digest
    binary_name: str


class BinaryOptions(LineOriented, GoalSubsystem):
    """Create a runnable binary."""

    name = "binary"

    required_union_implementations = (BinaryImplementation,)


class Binary(Goal):
    subsystem_cls = BinaryOptions


@goal_rule
async def create_binary(
    addresses: Addresses,
    console: Console,
    workspace: Workspace,
    options: BinaryOptions,
    distdir: DistDir,
) -> Binary:
    with options.line_oriented(console) as print_stdout:
        print_stdout(f"Generating binaries in `./{distdir.relpath}`")
        binaries = await MultiGet(Get[CreatedBinary](Address, address) for address in addresses)
        merged_digest = await Get[Digest](
            DirectoriesToMerge(tuple(binary.digest for binary in binaries))
        )
        result = workspace.materialize_directory(
            DirectoryToMaterialize(merged_digest, path_prefix=str(distdir.relpath))
        )
        for path in result.output_paths:
            print_stdout(f"Wrote {path}")
    return Binary(exit_code=0)


# TODO: possibly factor this out. Revisit after porting lint.py, fmt.py, and test.py to use the
#  Target API.
def implementations_with_supported_target_types(
    implementations: Iterable[Type[BinaryImplementation]],
    *,
    registered_target_types: RegisteredTargetTypes,
    union_membership: UnionMembership,
) -> str:
    implementations_to_target_types = {
        implementation: implementation.valid_target_types(
            registered_target_types.types, union_membership=union_membership
        )
        for implementation in implementations
    }
    return "\n".join(
        sorted(
            f"  * {implementation.__name__}, works with target types: "
            f"{sorted(target_type.alias for target_type in target_types)}"
            for implementation, target_types in implementations_to_target_types.items()
        )
    )


@rule
async def coordinator_of_binaries(
    wrapped_target: WrappedTarget,
    union_membership: UnionMembership,
    registered_target_types: RegisteredTargetTypes,
) -> CreatedBinary:
    target = wrapped_target.target
    binary_implementations: Iterable[Type[BinaryImplementation]] = union_membership.union_rules[
        BinaryImplementation
    ]
    valid_binary_implementations = [
        binary_implementation
        for binary_implementation in binary_implementations
        if binary_implementation.is_valid_target(target)
    ]
    if not valid_binary_implementations:
        all_implementations = implementations_with_supported_target_types(
            binary_implementations,
            registered_target_types=registered_target_types,
            union_membership=union_membership,
        )
        raise ValueError(
            f"None of the registered binary implementations work with {target.address} (target "
            f"type {repr(target.alias)}). All registered binary implementations:\n\n"
            f"{all_implementations}."
        )
    if len(valid_binary_implementations) > 1:
        valid_implementations = implementations_with_supported_target_types(
            valid_binary_implementations,
            registered_target_types=registered_target_types,
            union_membership=union_membership,
        )
        raise ValueError(
            f"Multiple of the registered binary implementations work for {target.address} "
            f"(target type {repr(target.alias)}). It is ambiguous which implementation to use. "
            f"Possible implementations:\n\n{valid_implementations}."
        )
    binary_implementation = valid_binary_implementations[0]
    return await Get[CreatedBinary](BinaryImplementation, binary_implementation.create(target))


def rules():
    return [create_binary, coordinator_of_binaries]
