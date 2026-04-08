# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
import logging
import os
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from pants.backend.project_info.incremental_dependents import (
    CachedEntry,
    compute_source_fingerprint,
    get_cache_path,
    load_persisted_graph,
    save_persisted_graph,
)
from pants.base.build_environment import get_buildroot
from pants.engine.addresses import Address, Addresses
from pants.engine.collection import DeduplicatedCollection
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.internals.graph import resolve_dependencies
from pants.engine.rules import collect_rules, concurrently, goal_rule, implicitly, rule
from pants.engine.target import (
    AllUnexpandedTargets,
    AlwaysTraverseDeps,
    Dependencies,
    DependenciesRequest,
)
from pants.option.option_types import BoolOption, EnumOption
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AddressToDependents:
    mapping: FrozenDict[Address, FrozenOrderedSet[Address]]


class DependentsOutputFormat(Enum):
    """Output format for listing dependents.

    text: List all dependents as a single list of targets in plain text.
    json: List all dependents as a mapping `{target: [dependents]}`.
    """

    text = "text"
    json = "json"


@rule(desc="Map all targets to their dependents", level=LogLevel.DEBUG)
async def map_addresses_to_dependents(
    all_targets: AllUnexpandedTargets,
) -> AddressToDependents:
    """Build a reverse dependency map (target -> set of its dependents).

    When incremental mode is enabled via the PANTS_INCREMENTAL_DEPENDENTS environment
    variable, the forward dependency graph is persisted to disk. On subsequent runs,
    only targets whose source files have changed need their dependencies re-resolved,
    dramatically reducing wall time for large repos.
    """
    if not os.environ.get("PANTS_INCREMENTAL_DEPENDENTS"):
        # Original behavior: resolve all dependencies from scratch.
        dependencies_per_target = await concurrently(
            resolve_dependencies(
                DependenciesRequest(
                    tgt.get(Dependencies),
                    should_traverse_deps_predicate=AlwaysTraverseDeps(),
                ),
                **implicitly(),
            )
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

    # --- Incremental mode ---
    start_time = time.time()
    buildroot = get_buildroot()
    cache_path = get_cache_path()

    # Step 1: Load previous graph
    previous = load_persisted_graph(cache_path, buildroot)
    logger.warning(
        "Incremental dep graph: loaded %d cached entries from %s",
        len(previous),
        cache_path,
    )

    # Step 2: Classify targets as cached or changed
    changed_targets = []
    cached_results: list[tuple[Address, CachedEntry]] = []

    for tgt in all_targets:
        spec = tgt.address.spec
        fingerprint = compute_source_fingerprint(tgt.address, buildroot)

        cached_entry = previous.get(spec)
        if cached_entry is not None and cached_entry.fingerprint == fingerprint:
            cached_results.append((tgt.address, cached_entry))
        else:
            changed_targets.append(tgt)

    cache_hits = len(cached_results)
    cache_misses = len(changed_targets)
    logger.warning(
        "Incremental dep graph: %d cached, %d changed (out of %d total targets)",
        cache_hits,
        cache_misses,
        len(all_targets),
    )

    # Step 3: Resolve deps only for changed targets
    if changed_targets:
        fresh_deps_per_target = await concurrently(
            resolve_dependencies(
                DependenciesRequest(
                    tgt.get(Dependencies),
                    should_traverse_deps_predicate=AlwaysTraverseDeps(),
                ),
                **implicitly(),
            )
            for tgt in changed_targets
        )
    else:
        fresh_deps_per_target = []

    # Step 4: Build the reverse dependency map from merged results
    address_to_dependents: dict[Address, set[Address]] = defaultdict(set)

    # Build a spec → Address lookup from all_targets for resolving cached specs
    spec_to_address: dict[str, Address] = {tgt.address.spec: tgt.address for tgt in all_targets}

    # Process cached results (deps stored as address spec strings)
    for addr, entry in cached_results:
        for dep_spec in entry.deps:
            dep_addr = spec_to_address.get(dep_spec)
            if dep_addr is not None:
                address_to_dependents[dep_addr].add(addr)

    # Process freshly resolved results
    for tgt, deps in zip(changed_targets, fresh_deps_per_target):
        for dep_addr in deps:
            address_to_dependents[dep_addr].add(tgt.address)

    # Step 5: Save the updated forward graph for next run
    new_entries: dict[str, CachedEntry] = {}

    # Carry forward cached entries
    for addr, entry in cached_results:
        new_entries[addr.spec] = entry

    # Add fresh entries
    for tgt, deps in zip(changed_targets, fresh_deps_per_target):
        spec = tgt.address.spec
        fingerprint = compute_source_fingerprint(tgt.address, buildroot)
        new_entries[spec] = CachedEntry(
            fingerprint=fingerprint,
            deps=tuple(dep.spec for dep in deps),
        )

    save_persisted_graph(cache_path, buildroot, new_entries)

    elapsed = time.time() - start_time
    logger.warning(
        "Incremental dep graph: completed in %.1fs (%d from cache, %d resolved fresh)",
        elapsed,
        cache_hits,
        cache_misses,
    )

    return AddressToDependents(
        FrozenDict(
            {
                addr: FrozenOrderedSet(dependents)
                for addr, dependents in address_to_dependents.items()
            }
        )
    )


@dataclass(frozen=True)
class DependentsRequest:
    addresses: FrozenOrderedSet[Address]
    transitive: bool
    include_roots: bool

    def __init__(
        self, addresses: Iterable[Address], *, transitive: bool, include_roots: bool
    ) -> None:
        object.__setattr__(self, "addresses", FrozenOrderedSet(addresses))
        object.__setattr__(self, "transitive", transitive)
        object.__setattr__(self, "include_roots", include_roots)


class Dependents(DeduplicatedCollection[Address]):
    sort_input = True


@rule(level=LogLevel.DEBUG)
async def find_dependents(
    request: DependentsRequest, address_to_dependents: AddressToDependents
) -> Dependents:
    check = set(request.addresses)
    known_dependents: set[Address] = set()
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


class DependentsSubsystem(LineOriented, GoalSubsystem):
    name = "dependents"
    help = "List all targets that depend on any of the input files/targets."

    transitive = BoolOption(
        default=False,
        help="List all transitive dependents. If unspecified, list direct dependents only.",
    )
    closed = BoolOption(
        default=False,
        help="Include the input targets in the output, along with the dependents.",
    )
    format = EnumOption(
        default=DependentsOutputFormat.text,
        help="Output format for listing dependents.",
    )


class DependentsGoal(Goal):
    subsystem_cls = DependentsSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY


async def list_dependents_as_plain_text(
    addresses: Addresses, dependents_subsystem: DependentsSubsystem, console: Console
) -> None:
    """Get dependents for given addresses and list them in the console as a single list."""
    dependents = await find_dependents(
        DependentsRequest(
            addresses,
            transitive=dependents_subsystem.transitive,
            include_roots=dependents_subsystem.closed,
        ),
        **implicitly(),
    )
    with dependents_subsystem.line_oriented(console) as print_stdout:
        for address in dependents:
            print_stdout(address.spec)


async def list_dependents_as_json(
    addresses: Addresses, dependents_subsystem: DependentsSubsystem, console: Console
) -> None:
    """Get dependents for given addresses and list them in the console in JSON."""
    dependents_group = await concurrently(
        find_dependents(
            DependentsRequest(
                (address,),
                transitive=dependents_subsystem.transitive,
                include_roots=dependents_subsystem.closed,
            ),
            **implicitly(),
        )
        for address in addresses
    )
    iterated_addresses = []
    for dependents in dependents_group:
        iterated_addresses.append(sorted([str(address) for address in dependents]))
    mapping = dict(zip([str(address) for address in addresses], iterated_addresses))
    output = json.dumps(mapping, indent=4)
    with dependents_subsystem.line_oriented(console) as print_stdout:
        print_stdout(output)


@goal_rule
async def dependents_goal(
    specified_addresses: Addresses, dependents_subsystem: DependentsSubsystem, console: Console
) -> DependentsGoal:
    if DependentsOutputFormat.text == dependents_subsystem.format:
        await list_dependents_as_plain_text(
            addresses=specified_addresses,
            dependents_subsystem=dependents_subsystem,
            console=console,
        )
    elif DependentsOutputFormat.json == dependents_subsystem.format:
        await list_dependents_as_json(
            addresses=specified_addresses,
            dependents_subsystem=dependents_subsystem,
            console=console,
        )
    return DependentsGoal(exit_code=0)


def rules():
    return collect_rules()
