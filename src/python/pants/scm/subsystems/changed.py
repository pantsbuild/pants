# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple, cast

from pants.base.deprecated import resolve_conflicting_options
from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.addresses import Address, Addresses
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.internals.mapper import AddressMapper
from pants.engine.internals.parser import HydratedStruct
from pants.engine.legacy.graph import _DependentGraph, target_types_from_build_file_aliases
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.goal.workspace import ScmWorkspace
from pants.option.option_value_container import OptionValueContainer
from pants.scm.scm import Scm
from pants.subsystem.subsystem import Subsystem


class DependeesOption(Enum):
    NONE = "none"
    DIRECT = "direct"
    TRANSITIVE = "transitive"


@dataclass(frozen=True)
class ChangedRequest:
    sources: Tuple[str, ...]
    dependees: DependeesOption


@dataclass(frozen=True)
class ChangedAddresses:
    """Light wrapper around the addresses referring to the changed targets."""

    addresses: Addresses


@rule
async def find_owners(
    build_configuration: BuildConfiguration,
    address_mapper: AddressMapper,
    changed_request: ChangedRequest,
) -> ChangedAddresses:
    owners = await Get(Owners, OwnersRequest(sources=changed_request.sources))

    # If the ChangedRequest does not require dependees, then we're done.
    if changed_request.dependees == DependeesOption.NONE:
        return ChangedAddresses(owners.addresses)

    # Otherwise: find dependees.
    all_addresses = await Get(Addresses, AddressSpecs((DescendantAddresses(""),)))
    all_structs = [
        s.value for s in await MultiGet(Get(HydratedStruct, Address, a) for a in all_addresses)
    ]

    bfa = build_configuration.registered_aliases()
    graph = _DependentGraph.from_iterable(
        target_types_from_build_file_aliases(bfa), address_mapper, all_structs
    )
    if changed_request.dependees == DependeesOption.DIRECT:
        return ChangedAddresses(Addresses(graph.dependents_of_addresses(owners.addresses)))
    return ChangedAddresses(Addresses(graph.transitive_dependents_of_addresses(owners.addresses)))


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

    def is_actionable(self) -> bool:
        return bool(self.since or self.diffspec)

    def changed_files(self, *, scm: Scm) -> List[str]:
        """Determines the files changed according to SCM/workspace and options."""
        workspace = ScmWorkspace(scm)
        if self.diffspec:
            return cast(List[str], workspace.changes_in(self.diffspec))

        changes_since = self.since or scm.current_rev_identifier
        return cast(List[str], workspace.touched_files(changes_since))


class Changed(Subsystem):
    """Tell Pants to detect what files and targets have changed from Git.

    See https://pants.readme.io/docs/advanced-target-selection.
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
            removal_version="2.0.1.dev0",
            removal_hint="Use `--changed-dependees` instead of `--changed-include-dependees`.",
        )
        register(
            "--fast",
            type=bool,
            default=False,
            help="Stop searching for owners once a source is mapped to at least one owning target.",
            removal_version="2.0.1.dev0",
            removal_hint="The option `--changed-fast` no longer does anything.",
        )


@dataclass(frozen=True)
class UncachedScmWrapper:
    """???/the salt is intended to be different every time, so the scm should avoid being memoized
    by the engine!"""

    scm: Scm
    salt: str

    @classmethod
    def create(cls, scm: Scm) -> "UncachedScmWrapper":
        return cls(scm=scm, salt=str(uuid.uuid4()),)


def rules():
    return [
        find_owners,
        RootRule(ChangedRequest),
        RootRule(UncachedScmWrapper),
    ]
