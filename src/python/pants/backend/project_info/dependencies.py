# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import dataclasses
import itertools
import json
from enum import Enum

from pants.engine.addresses import Addresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import AlwaysTraverseDeps, Target
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

    merged: List all dependencies as a single list of targets.
    json: List all dependencies as a mapping `{target: [dependencies]}`.
    """

    merged = "merged"
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
        default=DependenciesOutputFormat.merged,
        help="Output format for listing dependencies.",
    )


class Dependencies(Goal):
    subsystem_cls = DependenciesSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY

@dataclasses.dataclass
class TargetToDependencies:
    target: Target
    dependencies: Targets


@goal_rule
async def dependencies(
    console: Console, addresses: Addresses, dependencies_subsystem: DependenciesSubsystem
) -> Dependencies:
    # NB: We must preserve target generators for the roots, i.e. not replace with their
    # generated targets.
    target_roots = await Get(UnexpandedTargets, Addresses, addresses)
    # NB: When determining dependencies, though, we replace target generators with their
    # generated targets.

    if dependencies_subsystem.format == DependenciesOutputFormat.json:
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
        for targets in dependencies_per_target_root:
            iterated_targets.append([str(tgt.address) for tgt in targets])

        mapping = dict(zip(
            [str(tgt.address) for tgt in target_roots],
            iterated_targets
        ))
        output = json.dumps(mapping, indent=4)
        console.print_stdout(output)

    if dependencies_subsystem.format == DependenciesOutputFormat.merged:
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

    return Dependencies(exit_code=0)


def rules():
    return collect_rules()
