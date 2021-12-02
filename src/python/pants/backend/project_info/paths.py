# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
from collections import deque
from operator import attrgetter
from typing import Dict, Generator, cast

from pants.engine.addresses import Address, Addresses, UnparsedAddressInputs
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import Dependencies as DependenciesField
from pants.engine.target import (
    DependenciesRequest,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)


class PathsSubsystem(LineOriented, GoalSubsystem):
    name = "paths"
    help = "List the paths between two addresses."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--path-from",
            type=str,
            help="The path starting address",
        )

        register(
            "--path-to",
            type=str,
            help="The path end address",
        )

    @property
    def path_from(self) -> str:
        return cast(str, self.options.path_from)

    @property
    def path_to(self) -> str:
        return cast(str, self.options.path_to)


class PathsGoal(Goal):
    subsystem_cls = PathsSubsystem


def find_paths_breadth_first(
    adjacency_lists: Dict[Address, Targets], from_target: Address, to_target: Address
) -> Generator[Addresses, None, None]:
    """Yields the paths between from_target to to_target if they exist.

    The paths are returned ordered by length, shortest first. If there are cycles, it checks visited
    edges to prevent recrossing them.
    """

    if from_target == to_target:
        yield [from_target]
        return

    visited_edges = set()
    to_walk_paths = deque([[from_target]])

    while len(to_walk_paths) > 0:
        cur_path = to_walk_paths.popleft()
        target = cur_path[-1]

        if len(cur_path) > 1:
            prev_target = cur_path[-2]
        else:
            prev_target = None
        current_edge = (prev_target, target)

        if current_edge not in visited_edges:
            for dep in adjacency_lists[target]:
                dep_path = cur_path + [dep.address]
                if dep.address == to_target:
                    yield dep_path
                else:
                    to_walk_paths.append(dep_path)
            visited_edges.add(current_edge)


@goal_rule
async def paths(
    console: Console, addresses: Addresses, paths_subsystem: PathsSubsystem
) -> PathsGoal:

    path_from = paths_subsystem.path_from
    path_to = paths_subsystem.path_to

    if path_from is None:
        raise ValueError("Must set a --from-path")

    if path_to is None:
        raise ValueError("Must set a --to-path")

    root, destination = await Get(
        Addresses,
        UnparsedAddressInputs(values=[path_from, path_to], owning_address=None),
    )

    transitive_targets = await Get(
        TransitiveTargets, TransitiveTargetsRequest([root], include_special_cased_deps=True)
    )
    if not any(destination == dep.address for dep in transitive_targets.dependencies):
        raise ValueError("The destination is not a dependency of the source")

    adjacent_targets_per_target = await MultiGet(
        Get(
            Targets,
            DependenciesRequest(tgt.get(DependenciesField), include_special_cased_deps=True),
        )
        for tgt in transitive_targets.closure
    )

    transitive_targets_closure_addresses = map(attrgetter("address"), transitive_targets.closure)
    adjacency_lists = dict(zip(transitive_targets_closure_addresses, adjacent_targets_per_target))

    spec_paths = []
    for path in find_paths_breadth_first(adjacency_lists, root, destination):
        spec_path = [address.spec for address in path]
        spec_paths.append(spec_path)

    console.write_stdout(json.dumps(spec_paths, indent=2))

    return PathsGoal(exit_code=0)


def rules():
    return collect_rules()
