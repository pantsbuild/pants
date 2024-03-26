# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from pants.backend.project_info import dependents
from pants.backend.project_info.dependents import Dependents, DependentsRequest
from pants.base.build_environment import get_buildroot
from pants.base.deprecated import resolve_conflicting_options
from pants.engine.addresses import Address, Addresses
from pants.engine.collection import Collection
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.internals.mapper import SpecsFilter
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import UnexpandedTargets
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


@rule
async def find_changed_owners(
    request: ChangedRequest,
    specs_filter: SpecsFilter,
) -> ChangedAddresses:
    no_dependents = request.dependents == DependentsOption.NONE
    owners = await Get(
        Owners,
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
    dependents = await Get(
        Dependents,
        DependentsRequest(
            owners,
            transitive=request.dependents == DependentsOption.TRANSITIVE,
            include_roots=False,
        ),
    )
    result = FrozenOrderedSet(owners) | (dependents - owner_target_generators)
    if specs_filter.is_specified:
        # Finally, we must now filter out the result to only include what matches our tags, as the
        # last step of https://github.com/pantsbuild/pants/issues/15544.
        #
        # Note that we use `UnexpandedTargets` rather than `Targets` or `FilteredTargets` so that
        # we preserve target generators.
        result_as_tgts = await Get(UnexpandedTargets, Addresses(result))
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
        dependents = resolve_conflicting_options(
            old_option="dependees",
            new_option="dependents",
            old_scope=Changed.options_scope,
            new_scope=Changed.options_scope,
            old_container=options,
            new_container=options,
        )
        return cls(options.since, options.diffspec, dependents)

    @property
    def provided(self) -> bool:
        return bool(self.since) or bool(self.diffspec)

    def changed_files(self, git_worktree: GitWorktree) -> set[str]:
        """Determines the files changed according to SCM/workspace and options."""
        if self.diffspec:
            return git_worktree.changes_in(self.diffspec, relative_to=get_buildroot())

        changes_since = self.since or git_worktree.current_rev_identifier
        return git_worktree.changed_files(
            from_commit=changes_since, include_untracked=True, relative_to=get_buildroot()
        )

    def diff_hunks(
        self, git_worktree: GitWorktree, paths: Iterable[str]
    ) -> FrozenDict[str, tuple[Hunk, ...]]:
        """Determines the unified diff hunks changed according to SCM/workspace and options.

        More info on unified diff: https://www.gnu.org/software/diffutils/manual/html_node/Detailed-Unified.html
        """
        changes_since = self.since or git_worktree.current_rev_identifier
        return git_worktree.changed_files_lines(
            paths=paths,
            from_commit=changes_since,
            relative_to=get_buildroot(),
        )


class Changed(Subsystem):
    options_scope = "changed"
    help = help_text(
        f"""
        Tell Pants to detect what files and targets have changed from Git.

        See {doc_url('docs/using-pants/advanced-target-selection')}.
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
    dependees = EnumOption(
        default=DependentsOption.NONE,
        help="Include direct or transitive dependents of changed targets.",
        removal_version="2.23.0.dev0",
        removal_hint="Use --dependents instead",
    )


def rules():
    return [*collect_rules(), *dependents.rules()]
