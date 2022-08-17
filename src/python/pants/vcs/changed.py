# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, cast

from pants.backend.project_info import dependees
from pants.backend.project_info.dependees import Dependees, DependeesRequest
from pants.base.build_environment import get_buildroot
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
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import softwrap
from pants.vcs.git import GitWorktree


class DependeesOption(Enum):
    NONE = "none"
    DIRECT = "direct"
    TRANSITIVE = "transitive"


@dataclass(frozen=True)
class ChangedRequest:
    sources: tuple[str, ...]
    dependees: DependeesOption


class ChangedAddresses(Collection[Address]):
    pass


@rule
async def find_changed_owners(
    request: ChangedRequest, specs_filter: SpecsFilter
) -> ChangedAddresses:
    no_dependees = request.dependees == DependeesOption.NONE
    owners = await Get(
        Owners,
        OwnersRequest(
            request.sources,
            # If `--changed-dependees` is used, we cannot eagerly filter out root targets. We
            # need to first find their dependees, and only then should we filter. See
            # https://github.com/pantsbuild/pants/issues/15544
            filter_by_global_options=no_dependees,
            # Changing a BUILD file might impact the targets it defines.
            match_if_owning_build_file_included_in_sources=True,
        ),
    )
    if no_dependees:
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
    dependees = await Get(
        Dependees,
        DependeesRequest(
            owners,
            transitive=request.dependees == DependeesOption.TRANSITIVE,
            include_roots=False,
        ),
    )
    result = FrozenOrderedSet(owners) | (dependees - owner_target_generators)
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
    configured, so the normal mechanisms like `SubsystemRule` would not work properly.
    """

    since: str | None
    diffspec: str | None
    dependees: DependeesOption

    @classmethod
    def from_options(cls, options: OptionValueContainer) -> ChangedOptions:
        return cls(options.since, options.diffspec, options.dependees)

    @property
    def provided(self) -> bool:
        return bool(self.since) or bool(self.diffspec)

    def changed_files(self, git_worktree: GitWorktree) -> list[str]:
        """Determines the files changed according to SCM/workspace and options."""
        if self.diffspec:
            return cast(
                List[str], git_worktree.changes_in(self.diffspec, relative_to=get_buildroot())
            )

        changes_since = self.since or git_worktree.current_rev_identifier
        return cast(
            List[str],
            git_worktree.changed_files(
                from_commit=changes_since, include_untracked=True, relative_to=get_buildroot()
            ),
        )


class Changed(Subsystem):
    options_scope = "changed"
    help = softwrap(
        f"""
        Tell Pants to detect what files and targets have changed from Git.

        See {doc_url('advanced-target-selection')}.
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
    dependees = EnumOption(
        default=DependeesOption.NONE,
        help="Include direct or transitive dependees of changed targets.",
    )


def rules():
    return [*collect_rules(), *dependees.rules()]
