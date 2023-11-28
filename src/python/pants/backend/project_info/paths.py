# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from typing import Iterable

from pants.base.specs import Specs
from pants.base.specs_parser import SpecsParser
from pants.engine.addresses import Address
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, Outputting
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import (
    AlwaysTraverseDeps,
    Dependencies,
    DependenciesRequest,
    Target,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.option.option_types import StrOption


class PathsSubsystem(Outputting, GoalSubsystem):
    name = "paths"
    help = (
        "List the paths between two addresses. "
        "Either address may represent a group of targets, e.g. `--from=src/app/main.py --to=src/library::`."
    )

    from_ = StrOption(
        default=None,
        help="The path starting address",
    )

    to = StrOption(
        default=None,
        help="The path end address",
    )


class PathsGoal(Goal):
    subsystem_cls = PathsSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY


def find_paths_breadth_first(
    adjacency_lists: dict[Address, Targets], from_target: Address, to_target: Address
) -> Iterable[list[Address]]:
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
            prev_target: Address | None = cur_path[-2]
        else:
            prev_target = None
        current_edge = (prev_target, target)

        if current_edge not in visited_edges:
            for dep in adjacency_lists.get(target, []):
                dep_path = cur_path + [dep.address]
                if dep.address == to_target:
                    yield dep_path
                else:
                    to_walk_paths.append(dep_path)
            visited_edges.add(current_edge)


@dataclass
class SpecsPaths:
    paths: list[list[str]]


@dataclass
class SpecsPathsCollection:
    spec_paths: list[SpecsPaths]


@dataclass(frozen=True)
class RootDestinationPair:
    root: Target
    destination: Target


@dataclass(frozen=True)
class RootDestinationsPair:
    root: Target
    destinations: Targets


@rule(desc="Get paths between root and destination.")
async def get_paths_between_root_and_destination(pair: RootDestinationPair) -> SpecsPaths:
    transitive_targets = await Get(
        TransitiveTargets,
        TransitiveTargetsRequest(
            [pair.root.address], should_traverse_deps_predicate=AlwaysTraverseDeps()
        ),
    )

    adjacent_targets_per_target = await MultiGet(
        Get(
            Targets,
            DependenciesRequest(
                tgt.get(Dependencies), should_traverse_deps_predicate=AlwaysTraverseDeps()
            ),
        )
        for tgt in transitive_targets.closure
    )

    transitive_targets_closure_addresses = (t.address for t in transitive_targets.closure)
    adjacency_lists = dict(zip(transitive_targets_closure_addresses, adjacent_targets_per_target))

    spec_paths = []
    for path in find_paths_breadth_first(
        adjacency_lists, pair.root.address, pair.destination.address
    ):
        spec_path = [address.spec for address in path]
        spec_paths.append(spec_path)

    return SpecsPaths(paths=spec_paths)


@rule("Get paths between root and multiple destinations.")
async def get_paths_between_root_and_destinations(
    pair: RootDestinationsPair,
) -> SpecsPathsCollection:
    spec_paths = await MultiGet(
        Get(
            SpecsPaths,
            RootDestinationPair,
            RootDestinationPair(destination=destination, root=pair.root),
        )
        for destination in pair.destinations
    )
    return SpecsPathsCollection(spec_paths=list(spec_paths))


@goal_rule
async def paths(console: Console, paths_subsystem: PathsSubsystem) -> PathsGoal:
    path_from = paths_subsystem.from_
    path_to = paths_subsystem.to

    if path_from is None:
        raise ValueError("Must set --from")

    if path_to is None:
        raise ValueError("Must set --to")

    specs_parser = SpecsParser()

    from_tgts, to_tgts = await MultiGet(
        Get(
            Targets,
            Specs,
            specs_parser.parse_specs(
                [path_from],
                description_of_origin="the option `--paths-from`",
            ),
        ),
        Get(
            Targets,
            Specs,
            specs_parser.parse_specs(
                [path_to],
                description_of_origin="the option `--paths-to`",
            ),
        ),
    )

    all_spec_paths = []
    spec_paths = await MultiGet(
        Get(
            SpecsPathsCollection,
            RootDestinationsPair,
            RootDestinationsPair(root=root, destinations=to_tgts),
        )
        for root in from_tgts
    )

    for spec_path in spec_paths:
        for path in (p.paths for p in spec_path.spec_paths):
            all_spec_paths.extend(path)

    with paths_subsystem.output(console) as write_stdout:
        write_stdout(json.dumps(all_spec_paths, indent=2) + "\n")

    return PathsGoal(exit_code=0)


def rules():
    return collect_rules()
