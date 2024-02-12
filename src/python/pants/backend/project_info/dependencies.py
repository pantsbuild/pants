# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import itertools
import json
from enum import Enum

from pants.engine.addresses import Addresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import AlwaysTraverseDeps
from pants.engine.target import Dependencies as DependenciesField
from pants.engine.target import (
    DependenciesRequest,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
    UnexpandedTargets,
)
from pants.option.option_types import BoolOption, EnumOption


class DependenciesOutputFormat(Enum):
    """Output format for listing dependencies.

    text: List all dependencies as a single list of targets in plain text.
    json: List all dependencies as a mapping `{target: [dependencies]}`.
    """

    text = "text"
    json = "json"


class DependenciesSubsystem(LineOriented, GoalSubsystem):
    name = "dependencies"
    help = "List the dependencies of the input files/targets."

    transitive = BoolOption(
        default=False,
        help="List all transitive dependencies. If unspecified, list direct dependencies only.",
    )
    closed = BoolOption(
        default=False,
        help="Include the input targets in the output, along with the dependencies.",
    )
    format = EnumOption(
        default=DependenciesOutputFormat.text,
        help="Output format for listing dependencies.",
    )


class Dependencies(Goal):
    subsystem_cls = DependenciesSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY


async def list_dependencies_as_json(
    addresses: Addresses, dependencies_subsystem: DependenciesSubsystem, console: Console
) -> None:
    """Get dependencies for given addresses and list them in the console in JSON."""
    # NB: We must preserve target generators for the roots, i.e. not replace with their
    # generated targets.
    target_roots = await Get(UnexpandedTargets, Addresses, addresses)
    # NB: When determining dependencies, though, we replace target generators with their
    # generated targets.
    if dependencies_subsystem.transitive:
        transitive_targets_group = await MultiGet(
            Get(
                TransitiveTargets,
                TransitiveTargetsRequest(
                    (address,), should_traverse_deps_predicate=AlwaysTraverseDeps()
                ),
            )
            for address in addresses
        )

        iterated_targets = []
        for idx, transitive_targets in enumerate(transitive_targets_group):
            targets_collection = {
                str(tgt.address)
                for tgt in (
                    transitive_targets.closure
                    if dependencies_subsystem.closed
                    else transitive_targets.dependencies
                )
            }
            iterated_targets.append(sorted(targets_collection))

    else:
        dependencies_per_target_root = await MultiGet(
            Get(
                Targets,
                DependenciesRequest(
                    tgt.get(DependenciesField),
                    should_traverse_deps_predicate=AlwaysTraverseDeps(),
                ),
            )
            for tgt in target_roots
        )

        iterated_targets = []
        for idx, targets in enumerate(dependencies_per_target_root):
            targets_collection = {str(tgt.address) for tgt in targets}
            if dependencies_subsystem.closed:
                targets_collection.add(str(target_roots[idx].address))
            iterated_targets.append(sorted(targets_collection))

    # The assumption is that when iterating the targets and sending dependency requests
    # for them, the lists of dependencies are returned in the very same order.
    mapping = dict(zip([str(tgt.address) for tgt in target_roots], iterated_targets))
    output = json.dumps(mapping, indent=4)
    console.print_stdout(output)


async def list_dependencies_as_plain_text(
    addresses: Addresses, dependencies_subsystem: DependenciesSubsystem, console: Console
) -> None:
    """Get dependencies for given addresses and list them in the console as a single list."""
    if dependencies_subsystem.transitive:
        transitive_targets = await Get(
            TransitiveTargets,
            TransitiveTargetsRequest(
                addresses, should_traverse_deps_predicate=AlwaysTraverseDeps()
            ),
        )
        targets = Targets(transitive_targets.dependencies)
    else:
        # NB: We must preserve target generators for the roots, i.e. not replace with their
        # generated targets.
        target_roots = await Get(UnexpandedTargets, Addresses, addresses)
        # NB: When determining dependencies, though, we replace target generators with their
        # generated targets.
        dependencies_per_target_root = await MultiGet(
            Get(
                Targets,
                DependenciesRequest(
                    tgt.get(DependenciesField),
                    should_traverse_deps_predicate=AlwaysTraverseDeps(),
                ),
            )
            for tgt in target_roots
        )
        targets = Targets(itertools.chain.from_iterable(dependencies_per_target_root))

    address_strings = {addr.spec for addr in addresses} if dependencies_subsystem.closed else set()
    for tgt in targets:
        address_strings.add(tgt.address.spec)

    with dependencies_subsystem.line_oriented(console) as print_stdout:
        for address in sorted(address_strings):
            print_stdout(address)


@goal_rule
async def dependencies(
    console: Console, addresses: Addresses, dependencies_subsystem: DependenciesSubsystem
) -> Dependencies:
    if DependenciesOutputFormat.text == dependencies_subsystem.format:
        await list_dependencies_as_plain_text(
            addresses=addresses,
            dependencies_subsystem=dependencies_subsystem,
            console=console,
        )

    elif DependenciesOutputFormat.json == dependencies_subsystem.format:
        await list_dependencies_as_json(
            addresses=addresses,
            dependencies_subsystem=dependencies_subsystem,
            console=console,
        )

    return Dependencies(exit_code=0)


def rules():
    return collect_rules()
