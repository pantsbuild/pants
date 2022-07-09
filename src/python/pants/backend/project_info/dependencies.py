# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools

from pants.engine.addresses import Addresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import Dependencies as DependenciesField
from pants.engine.target import (
    DependenciesRequest,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
    UnexpandedTargets,
)
from pants.option.option_types import BoolOption


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


class Dependencies(Goal):
    subsystem_cls = DependenciesSubsystem


@goal_rule
async def dependencies(
    console: Console, addresses: Addresses, dependencies_subsystem: DependenciesSubsystem
) -> Dependencies:
    if dependencies_subsystem.transitive:
        transitive_targets = await Get(
            TransitiveTargets, TransitiveTargetsRequest(addresses, include_special_cased_deps=True)
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
                DependenciesRequest(tgt.get(DependenciesField), include_special_cased_deps=True),
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
