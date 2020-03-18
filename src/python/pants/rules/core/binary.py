# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Type

from pants.build_graph.address import Address
from pants.engine.addressable import Addresses
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoriesToMerge, DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.objects import union
from pants.engine.rules import UnionMembership, goal_rule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import Target, WrappedTarget
from pants.rules.core.distdir import DistDir


@union
class BinaryImplementation(ABC):
    @staticmethod
    @abstractmethod
    def is_valid_target(tgt: Target) -> bool:
        pass

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
    wrapped_target: WrappedTarget, union_membership: UnionMembership
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
        all_implementations = sorted(
            binary_implementation.__name__ for binary_implementation in binary_implementations
        )
        # TODO: improve this message even more by calculating exactly which targets work with each
        #  binary implementation, e.g.
        #
        #   All registered binary implementations:
        #     * PythonBinaryImplementation, works with target types: [`python_binary`, `my_custom_python_binary`]
        #     * JavaBinaryImplementation, works with target types: [`java_binary`]
        #
        # Ensure that this works with plugin fields...which is tricky because Target.has_fields()
        # is currently an instance method so that it can dynamically register any plugin fields at
        # constructor time. We need a classmethod. What should that be called to disambiguate
        # between Target.has_fields()? We also still need to call the helper method
        # Target._find_registered_field_subclass() to ensure that we support subclasses of Fields.
        raise ValueError(
            f"No registered binary implementations work with {target.address} (target type "
            f"{repr(target.alias)}). All registered binary implementations: {all_implementations}."
        )
    if len(valid_binary_implementations) > 1:
        valid_implementations = sorted(
            binary_implementation.__name__ for binary_implementation in valid_binary_implementations
        )
        raise ValueError(
            f"Multiple registered binary implementations work for {target.address} "
            f"(target type {repr(target.alias)}). It is ambiguous which implementation to use. "
            f"Possible implementations: {valid_implementations}."
        )
    binary_implementation = valid_binary_implementations[0]
    return await Get[CreatedBinary](BinaryImplementation, binary_implementation.create(target))


def rules():
    return [create_binary, coordinator_of_binaries]
