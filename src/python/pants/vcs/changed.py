# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple, cast

from pants.backend.project_info import dependees
from pants.backend.project_info.dependees import Dependees, DependeesRequest
from pants.base.build_environment import get_buildroot
from pants.base.deprecated import resolve_conflicting_options
from pants.engine.addresses import Address
from pants.engine.collection import Collection
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.rules import Get, collect_rules, rule
from pants.option.option_value_container import OptionValueContainer
from pants.option.subsystem import Subsystem
from pants.vcs.git import Git


class DependeesOption(Enum):
    NONE = "none"
    DIRECT = "direct"
    TRANSITIVE = "transitive"


@dataclass(frozen=True)
class ChangedRequest:
    sources: Tuple[str, ...]
    dependees: DependeesOption


class ChangedAddresses(Collection[Address]):
    pass


@rule
async def find_changed_owners(request: ChangedRequest) -> ChangedAddresses:
    owners = await Get(Owners, OwnersRequest(request.sources))
    if request.dependees == DependeesOption.NONE:
        return ChangedAddresses(owners)
    dependees_with_roots = await Get(
        Dependees,
        DependeesRequest(
            owners,
            transitive=request.dependees == DependeesOption.TRANSITIVE,
            include_roots=True,
        ),
    )
    return ChangedAddresses(dependees_with_roots)


@dataclass(frozen=True)
class ChangedOptions:
    """A wrapper for the options from the `Changed` Subsystem.

    This is necessary because parsing of these options happens before conventional subsystems are
    configured, so the normal mechanisms like `SubsystemRule` would not work properly.
    """

    since: Optional[str]
    diffspec: Optional[str]
    dependees: DependeesOption

    @classmethod
    def from_options(cls, options: OptionValueContainer) -> "ChangedOptions":
        since = resolve_conflicting_options(
            old_option="changes_since",
            new_option="since",
            old_scope="changed",
            new_scope="changed",
            old_container=options,
            new_container=options,
        )
        dependees = resolve_conflicting_options(
            old_option="include_dependees",
            new_option="dependees",
            old_scope="changed",
            new_scope="changed",
            old_container=options,
            new_container=options,
        )
        return cls(since, options.diffspec, dependees)

    @property
    def provided(self) -> bool:
        return bool(self.since) or bool(self.diffspec)

    def changed_files(self, git: Git) -> List[str]:
        """Determines the files changed according to SCM/workspace and options."""
        if self.diffspec:
            return cast(List[str], git.changes_in(self.diffspec, relative_to=get_buildroot()))

        changes_since = self.since or git.current_rev_identifier
        return cast(
            List[str],
            git.changed_files(
                from_commit=changes_since, include_untracked=True, relative_to=get_buildroot()
            ),
        )


class Changed(Subsystem):
    """Tell Pants to detect what files and targets have changed from Git.

    See https://www.pantsbuild.org/docs/advanced-target-selection.
    """

    options_scope = "changed"

    @classmethod
    def register_options(cls, register):
        register(
            "--since",
            type=str,
            default=None,
            help="Calculate changes since this Git spec (commit range/SHA/ref).",
        )
        register(
            "--changes-since",
            "--parent",
            type=str,
            default=None,
            removal_version="2.1.0.dev0",
            removal_hint=(
                "Use `--changed-since` instead of `--changed-parent` or `--changed-changes-since`."
            ),
            help="Calculate changes since this tree-ish/scm ref.",
        )
        register(
            "--diffspec",
            type=str,
            default=None,
            help="Calculate changes contained within a given Git spec (commit range/SHA/ref).",
        )
        register(
            "--dependees",
            type=DependeesOption,
            default=DependeesOption.NONE,
            help="Include direct or transitive dependees of changed targets.",
        )
        register(
            "--include-dependees",
            type=DependeesOption,
            default=DependeesOption.NONE,
            help="Include direct or transitive dependees of changed targets.",
            removal_version="2.1.0.dev0",
            removal_hint="Use `--changed-dependees` instead of `--changed-include-dependees`.",
        )
        register(
            "--fast",
            type=bool,
            default=False,
            help="Stop searching for owners once a source is mapped to at least one owning target.",
            removal_version="2.1.0.dev0",
            removal_hint="The option `--changed-fast` no longer does anything.",
        )


def rules():
    return [*collect_rules(), *dependees.rules()]
