# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
from collections import defaultdict
from enum import Enum
from typing import Iterable, Mapping, Set

from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.engine.addresses import Address, Addresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import Dependencies, DependenciesRequest, Targets


class DependeesOutputFormat(Enum):
    text = "text"
    json = "json"


class DependeesOptions(LineOriented, GoalSubsystem):
    """List all targets that depend on any of the input targets."""

    name = "dependees2"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--transitive",
            default=False,
            type=bool,
            help=(
                "List all targets which transitively depend on the specified target, rather than "
                "only targets that directly depend on the specified target."
            ),
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


class Dependees(Goal):
    subsystem_cls = DependeesOptions


def calculate_dependees(
    address_to_dependees: Mapping[Address, Set[Address]],
    roots: Iterable[Address],
    *,
    transitive: bool
) -> Set[Address]:
    check = set(roots)
    known_dependents: Set[Address] = set()
    while True:
        dependents = set(known_dependents)
        for target in check:
            dependents.update(address_to_dependees[target])
        check = dependents - known_dependents
        if not check or not transitive:
            return dependents - set(roots)
        known_dependents = dependents


@goal_rule
async def dependees_goal(
    specified_addresses: Addresses, options: DependeesOptions, console: Console
) -> Dependees:
    # Get every target in the project so that we can iterate over them to find their dependencies.
    all_targets = await Get[Targets](AddressSpecs([DescendantAddresses("")]))
    dependencies_per_target = await MultiGet(
        Get[Addresses](DependenciesRequest(tgt.get(Dependencies))) for tgt in all_targets
    )

    address_to_dependees = defaultdict(set)
    for tgt, dependencies in zip(all_targets, dependencies_per_target):
        for dependency in dependencies:
            address_to_dependees[dependency].add(tgt.address)

    # JSON should output each distinct specified target with its dependees, unlike the `text`
    # format flattening into a single set.
    if options.values.output_format == DependeesOutputFormat.json:
        json_result = {}
        for specified_address in specified_addresses:
            dependees = calculate_dependees(
                address_to_dependees, [specified_address], transitive=options.values.transitive
            )
            if options.values.closed:
                dependees.add(specified_address)
            json_result[specified_address.spec] = sorted(addr.spec for addr in dependees)
        with options.line_oriented(console) as print_stdout:
            print_stdout(json.dumps(json_result, indent=4, separators=(",", ": "), sort_keys=True))
        return Dependees(exit_code=0)

    # Filter `address_to_dependees` based on the specified addresses, and flatten it into a
    # single set.
    result_addresses = calculate_dependees(
        address_to_dependees, specified_addresses, transitive=options.values.transitive
    )
    if options.values.closed:
        result_addresses |= set(specified_addresses)

    with options.line_oriented(console) as print_stdout:
        for address in sorted(result_addresses):
            print_stdout(address)
    return Dependees(exit_code=0)


def rules():
    return [dependees_goal]
