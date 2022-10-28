# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Set

from pants.engine.addresses import Address, Addresses
from pants.engine.collection import DeduplicatedCollection
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import AllUnexpandedTargets, Dependencies, DependenciesRequest
from pants.option.option_types import BoolOption
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet


@dataclass(frozen=True)
class AddressToDependents:
    mapping: FrozenDict[Address, FrozenOrderedSet[Address]]


@rule(desc="Map all targets to their dependents", level=LogLevel.DEBUG)
async def map_addresses_to_dependents(all_targets: AllUnexpandedTargets) -> AddressToDependents:
    dependencies_per_target = await MultiGet(
        Get(Addresses, DependenciesRequest(tgt.get(Dependencies), include_special_cased_deps=True))
        for tgt in all_targets
    )

    address_to_dependents = defaultdict(set)
    for tgt, dependencies in zip(all_targets, dependencies_per_target):
        for dependency in dependencies:
            address_to_dependents[dependency].add(tgt.address)
    return AddressToDependents(
        FrozenDict(
            {
                addr: FrozenOrderedSet(dependents)
                for addr, dependents in address_to_dependents.items()
            }
        )
    )


@frozen_after_init
@dataclass(unsafe_hash=True)
class DependentsRequest:
    addresses: FrozenOrderedSet[Address]
    transitive: bool
    include_roots: bool

    def __init__(
        self, addresses: Iterable[Address], *, transitive: bool, include_roots: bool
    ) -> None:
        self.addresses = FrozenOrderedSet(addresses)
        self.transitive = transitive
        self.include_roots = include_roots


class Dependents(DeduplicatedCollection[Address]):
    sort_input = True


@rule(level=LogLevel.DEBUG)
def find_dependents(
    request: DependentsRequest, address_to_dependents: AddressToDependents
) -> Dependents:
    check = set(request.addresses)
    known_dependents: Set[Address] = set()
    while True:
        dependents = set(known_dependents)
        for target in check:
            target_dependents = address_to_dependents.mapping.get(target, FrozenOrderedSet())
            dependents.update(target_dependents)
        check = dependents - known_dependents
        if not check or not request.transitive:
            result = (
                dependents | set(request.addresses)
                if request.include_roots
                else dependents - set(request.addresses)
            )
            return Dependents(result)
        known_dependents = dependents


class DependeesSubsystem(LineOriented, GoalSubsystem):
    name = "dependees"
    help = "List all targets that depend on any of the input files/targets."

    transitive = BoolOption(
        default=False,
        help="List all transitive dependees. If unspecified, list direct dependees only.",
    )
    closed = BoolOption(
        default=False,
        help="Include the input targets in the output, along with the dependees.",
    )


class DependeesGoal(Goal):
    subsystem_cls = DependeesSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY


@goal_rule
async def dependees_goal(
    specified_addresses: Addresses, dependees_subsystem: DependeesSubsystem, console: Console
) -> DependeesGoal:
    dependees = await Get(
        Dependents,
        DependentsRequest(
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
