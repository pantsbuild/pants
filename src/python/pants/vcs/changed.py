# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from pants.backend.project_info import dependents
from pants.backend.project_info.dependents import DependentsRequest, find_dependents
from pants.base.build_environment import get_buildroot
from pants.engine.addresses import Address, Addresses
from pants.engine.collection import Collection
from pants.engine.internals.graph import (
    OwnersRequest,
    find_owners,
    resolve_dependencies,
    resolve_unexpanded_targets,
)
from pants.engine.internals.mapper import SpecsFilter
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import (
    AllUnexpandedTargets,
    AlwaysTraverseDeps,
    Dependencies,
    DependenciesRequest,
    Target,
)
from pants.option.option_types import EnumOption, StrOption
from pants.option.option_value_container import OptionValueContainer
from pants.option.subsystem import Subsystem
from pants.util.docutil import doc_url
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import help_text
from pants.vcs.git import GitWorktree
from pants.vcs.hunk import Hunk, TextBlocks


class DependentsOption(Enum):
    NONE = "none"
    DIRECT = "direct"
    TRANSITIVE = "transitive"


@dataclass(frozen=True)
class ChangedRequest:
    sources: tuple[str, ...]
    sources_blocks: FrozenDict[str, TextBlocks]
    dependents: DependentsOption


class ChangedAddresses(Collection[Address]):
    pass


async def _find_dependents_via_forward_bfs(
    seed_targets: list[Target],
    owners: frozenset[Address],
    matched_addrs: frozenset[Address],
) -> FrozenOrderedSet[Address]:
    """BFS forward from seed_targets, build a reverse dep map, then walk from owners.

    This avoids building the full reverse dependency graph for ALL targets in the repo.
    Instead, we only resolve dependencies for targets reachable from seed_targets,
    which skips target types irrelevant to the filtered set (e.g., Docker, Helm, Shell
    targets when filtering for python_test).
    """
    # Phase 1: BFS from seed targets to build forward dependency graph.
    visited: dict[Address, Target] = {tgt.address: tgt for tgt in seed_targets}
    forward_deps: dict[Address, tuple[Address, ...]] = {}
    queue: list[Target] = list(seed_targets)

    while queue:
        deps_per_target = await concurrently(
            resolve_dependencies(
                DependenciesRequest(
                    tgt.get(Dependencies),
                    should_traverse_deps_predicate=AlwaysTraverseDeps(),
                ),
                **implicitly(),
            )
            for tgt in queue
        )

        next_addrs: set[Address] = set()
        for tgt, dep_addrs in zip(queue, deps_per_target):
            forward_deps[tgt.address] = tuple(dep_addrs)
            for dep_addr in dep_addrs:
                if dep_addr not in visited:
                    next_addrs.add(dep_addr)

        if not next_addrs:
            break

        new_targets = await resolve_unexpanded_targets(
            Addresses(FrozenOrderedSet(next_addrs))
        )
        for tgt in new_targets:
            visited[tgt.address] = tgt
        queue = list(new_targets)

    # Phase 2: Invert to get reverse dependency map (within the visited subgraph).
    reverse_deps: dict[Address, list[Address]] = defaultdict(list)
    for addr, deps in forward_deps.items():
        for dep_addr in deps:
            reverse_deps[dep_addr].append(addr)

    # Phase 3: BFS from owners through the reverse map to find reachable matched targets.
    found: set[Address] = set()
    bfs_visited: set[Address] = set()
    bfs_queue = [addr for addr in owners if addr in reverse_deps or addr in matched_addrs]

    while bfs_queue:
        addr = bfs_queue.pop()
        if addr in bfs_visited:
            continue
        bfs_visited.add(addr)
        if addr in matched_addrs:
            found.add(addr)
        for rev_dep in reverse_deps.get(addr, ()):
            if rev_dep not in bfs_visited:
                bfs_queue.append(rev_dep)

    return FrozenOrderedSet(found)


@rule
async def find_changed_owners(
    request: ChangedRequest,
    specs_filter: SpecsFilter,
    all_unexpanded_targets: AllUnexpandedTargets,
) -> ChangedAddresses:
    no_dependents = request.dependents == DependentsOption.NONE
    owners = await find_owners(
        OwnersRequest(
            request.sources,
            # If `--changed-dependents` is used, we cannot eagerly filter out root targets. We
            # need to first find their dependents, and only then should we filter. See
            # https://github.com/pantsbuild/pants/issues/15544
            filter_by_global_options=no_dependents,
            # Changing a BUILD file might impact the targets it defines.
            match_if_owning_build_file_included_in_sources=True,
            sources_blocks=request.sources_blocks,
        ),
        **implicitly(),
    )

    if no_dependents:
        return ChangedAddresses(owners)

    # See https://github.com/pantsbuild/pants/issues/15313. We filter out target generators because
    # they are not useful as aliases for their generated targets in the context of
    # `--changed-since`. Including them makes it look like all sibling targets from the same
    # target generator have also changed.
    #
    # However, we also must be careful to preserve if target generators are direct owners, which
    # happens when a generated file is deleted.
    owner_target_generators = FrozenOrderedSet(
        addr.maybe_convert_to_target_generator() for addr in owners if addr.is_generated_target
    )

    if specs_filter.is_specified and request.dependents == DependentsOption.TRANSITIVE:
        # Optimization: instead of building the full reverse dependency graph for ALL targets
        # (which requires resolving dependencies for every target in the repo via
        # map_addresses_to_dependents), we build a restricted forward dependency graph starting
        # only from targets matching the filter, then invert it. This skips dependency
        # resolution for targets that are unreachable from the filtered set (e.g., Docker,
        # Helm, Shell targets when filtering for python_test).
        owners_set = frozenset(addr for addr in owners)
        owners_with_generators = owners_set | frozenset(owner_target_generators)

        matched_targets = [tgt for tgt in all_unexpanded_targets if specs_filter.matches(tgt)]
        matched_addr_set = frozenset(tgt.address for tgt in matched_targets)

        if matched_targets:
            dependent_addrs = await _find_dependents_via_forward_bfs(
                matched_targets, owners_with_generators, matched_addr_set
            )
        else:
            dependent_addrs = FrozenOrderedSet()

        # Include direct owners that match the filter, plus discovered dependents.
        # Exclude owner_target_generators per existing logic.
        result = FrozenOrderedSet(owners) | (dependent_addrs - owner_target_generators)

        # Apply specs_filter to the final result since owners were found without filtering.
        result_as_tgts = await resolve_unexpanded_targets(Addresses(result))
        result = FrozenOrderedSet(
            tgt.address for tgt in result_as_tgts if specs_filter.matches(tgt)
        )
        return ChangedAddresses(result)

    # Fall back to the original approach: build the full reverse dependency graph.
    dependents_result = await find_dependents(
        DependentsRequest(
            owners,
            transitive=request.dependents == DependentsOption.TRANSITIVE,
            include_roots=False,
        ),
        **implicitly(),
    )
    result = FrozenOrderedSet(owners) | (dependents_result - owner_target_generators)
    if specs_filter.is_specified:
        # Finally, we must now filter out the result to only include what matches our tags, as the
        # last step of https://github.com/pantsbuild/pants/issues/15544.
        #
        # Note that we use `UnexpandedTargets` rather than `Targets` or `FilteredTargets` so that
        # we preserve target generators.
        result_as_tgts = await resolve_unexpanded_targets(Addresses(result))
        result = FrozenOrderedSet(
            tgt.address for tgt in result_as_tgts if specs_filter.matches(tgt)
        )

    return ChangedAddresses(result)


@dataclass(frozen=True)
class ChangedOptions:
    """A wrapper for the options from the `Changed` Subsystem.

    This is necessary because parsing of these options happens before conventional subsystems are
    configured, so the normal mechanisms like `Subsystem.rules()` would not work properly.
    """

    since: str | None
    diffspec: str | None
    dependents: DependentsOption

    @classmethod
    def from_options(cls, options: OptionValueContainer) -> ChangedOptions:
        return cls(options.since, options.diffspec, options.dependents)

    @property
    def provided(self) -> bool:
        return bool(self.since) or bool(self.diffspec)

    def changed_files(self, git_worktree: GitWorktree) -> set[str]:
        """Determines the files changed according to SCM/workspace and options."""
        if self.diffspec:
            return git_worktree.changes_in(self.diffspec, relative_to=get_buildroot())

        changes_since = self.since or git_worktree.current_rev_identifier
        return git_worktree.changed_files(
            from_commit=changes_since,
            include_untracked=True,
            relative_to=get_buildroot(),
        )

    def diff_hunks(
        self, git_worktree: GitWorktree, paths: Iterable[str]
    ) -> dict[str, tuple[Hunk, ...]]:
        """Determines the unified diff hunks changed according to SCM/workspace and options.

        More info on unified diff: https://www.gnu.org/software/diffutils/manual/html_node/Detailed-Unified.html
        """
        changes_since = self.since or git_worktree.current_rev_identifier
        return git_worktree.changed_files_lines(
            paths,
            from_commit=changes_since,
            include_untracked=True,
            relative_to=get_buildroot(),
        )


class Changed(Subsystem):
    options_scope = "changed"
    help = help_text(
        f"""
        Tell Pants to detect what files and targets have changed from Git.

        See {doc_url("docs/using-pants/advanced-target-selection")}.
        """
    )

    since = StrOption(
        default=None,
        help="Calculate changes since this Git spec (commit range/SHA/ref).",
    )
    diffspec = StrOption(
        default=None,
        help="Calculate changes contained within a given Git spec (commit range/SHA/ref).",
    )
    dependents = EnumOption(
        default=DependentsOption.NONE,
        help="Include direct or transitive dependents of changed targets.",
    )


def rules():
    return [*collect_rules(), *dependents.rules()]
