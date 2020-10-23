# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Set, cast

from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.engine.addresses import Address, Addresses
from pants.engine.collection import DeduplicatedCollection
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import Dependencies, DependenciesRequest, Targets, UnexpandedTargets
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet


@dataclass(frozen=True)
class AddressToDependees:
    mapping: FrozenDict[Address, FrozenOrderedSet[Address]]


@rule(level=LogLevel.DEBUG)
async def map_addresses_to_dependees() -> AddressToDependees:
    # Get every target in the project so that we can iterate over them to find their dependencies.
    all_expanded_targets, all_explicit_targets = await MultiGet(
        Get(Targets, AddressSpecs([DescendantAddresses("")])),
        Get(UnexpandedTargets, AddressSpecs([DescendantAddresses("")])),
    )
    all_targets = {*all_expanded_targets, *all_explicit_targets}
    dependencies_per_target = await MultiGet(
        Get(Addresses, DependenciesRequest(tgt.get(Dependencies), include_special_cased_deps=True))
        for tgt in all_targets
    )

    address_to_dependees = defaultdict(set)
    for tgt, dependencies in zip(all_targets, dependencies_per_target):
        for dependency in dependencies:
            address_to_dependees[dependency].add(tgt.address)
    return AddressToDependees(
        FrozenDict(
            {addr: FrozenOrderedSet(dependees) for addr, dependees in address_to_dependees.items()}
        )
    )


@frozen_after_init
@dataclass(unsafe_hash=True)
class DependeesRequest:
    addresses: FrozenOrderedSet[Address]
    transitive: bool
    include_roots: bool

    def __init__(
        self, addresses: Iterable[Address], *, transitive: bool, include_roots: bool
    ) -> None:
        self.addresses = FrozenOrderedSet(addresses)
        self.transitive = transitive
        self.include_roots = include_roots


class Dependees(DeduplicatedCollection[Address]):
    sort_input = True


@rule(level=LogLevel.DEBUG)
def find_dependees(
    request: DependeesRequest, address_to_dependees: AddressToDependees
) -> Dependees:
    check = set(request.addresses)
    known_dependents: Set[Address] = set()
    while True:
        dependents = set(known_dependents)
        for target in check:
            target_dependees = address_to_dependees.mapping.get(target, FrozenOrderedSet())
            dependents.update(target_dependees)
        check = dependents - known_dependents
        if not check or not request.transitive:
            result = (
                dependents | set(request.addresses)
                if request.include_roots
                else dependents - set(request.addresses)
            )
            return Dependees(result)
        known_dependents = dependents


class DependeesOutputFormat(Enum):
    text = "text"
    json = "json"


class DependeesSubsystem(LineOriented, GoalSubsystem):
    """List all targets that depend on any of the input files/targets."""

    name = "dependees"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--transitive",
            default=False,
            type=bool,
            help="List all transitive dependees, instead of only direct dependees.",
        )
        register(
            "--closed",
            type=bool,
            default=False,
            help="Include the input targets in the output, along with the dependees.",
        )
        register(
            "--output-format",
            type=DependeesOutputFormat,
            default=DependeesOutputFormat.text,
            help=(
                "Use `text` for a flattened list of target addresses; use `json` for each key to be "
                "the address of one of the specified targets, with its value being "
                "a list of that target's dependees, e.g. `{':example': [':dep1', ':dep2']}`."
            ),
        )

    @property
    def transitive(self) -> bool:
        return cast(bool, self.options.transitive)

    @property
    def closed(self) -> bool:
        return cast(bool, self.options.closed)

    @property
    def output_format(self) -> DependeesOutputFormat:
        return cast(DependeesOutputFormat, self.options.output_format)


class DependeesGoal(Goal):
    subsystem_cls = DependeesSubsystem


@goal_rule
async def dependees_goal(
    specified_addresses: Addresses, dependees_subsystem: DependeesSubsystem, console: Console
) -> DependeesGoal:
    if dependees_subsystem.output_format == DependeesOutputFormat.json:
        dependees_per_target = await MultiGet(
            Get(
                Dependees,
                DependeesRequest(
                    [specified_address],
                    transitive=dependees_subsystem.transitive,
                    include_roots=dependees_subsystem.closed,
                ),
            )
            for specified_address in specified_addresses
        )
        json_result = {
            specified_address.spec: [dependee.spec for dependee in dependees]
            for specified_address, dependees in zip(specified_addresses, dependees_per_target)
        }
        with dependees_subsystem.line_oriented(console) as print_stdout:
            print_stdout(json.dumps(json_result, indent=4, separators=(",", ": "), sort_keys=True))
        return DependeesGoal(exit_code=0)

    dependees = await Get(
        Dependees,
        DependeesRequest(
            specified_addresses,
            transitive=dependees_subsystem.transitive,
            include_roots=dependees_subsystem.closed,
        ),
    )
    with dependees_subsystem.line_oriented(console) as print_stdout:
        for address in dependees:
            print_stdout(address.spec)
    return DependeesGoal(exit_code=0)


def rules():
    return collect_rules()
