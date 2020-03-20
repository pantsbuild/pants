# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
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
        all_valid_target_types = itertools.chain.from_iterable(
            implementation.valid_target_types(
                registered_target_types.types, union_membership=union_membership
            )
            for implementation in binary_implementations
        )
        formatted_target_types = sorted(target_type.alias for target_type in all_valid_target_types)
        # TODO: this is a leaky abstraction that the error message knows this rule is being used
        #  by `run` and `binary`. How should this be handled? A custom goal author could depend on
        #  this error message too and the error would now be lying.
        raise ValueError(
            f"The `run` and `binary` goals only work with the following target types: "
            f"{formatted_target_types}\n\nYou used {target.address} with target type "
            f"{repr(target.alias)}."
        )
    # TODO: we must use this check when running `./v2 run` because we should only run one target
    #  with one implementation. But, we don't necessarily need to enforce this with `./v2 binary`.
    #  See https://github.com/pantsbuild/pants/pull/9345#discussion_r395221542 for some possible
    #  semantics for `./v2 binary`.
    if len(valid_binary_implementations) > 1:
        possible_implementations = sorted(
            implementation.__name__ for implementation in valid_binary_implementations
        )
        # TODO: improve this error message. (It's never actually triggered yet because we only have
        #  Python implemented with V2.) A better error message would explain to users how they can
        #  resolve the issue.
        raise ValueError(
            f"Multiple of the registered binary implementations work for {target.address} "
            f"(target type {repr(target.alias)}). It is ambiguous which implementation to use. "
            f"Possible implementations: {possible_implementations}."
        )
    binary_implementation = valid_binary_implementations[0]
    return await Get[CreatedBinary](BinaryImplementation, binary_implementation.create(target))


def rules():
    return [create_binary, coordinator_of_binaries]
