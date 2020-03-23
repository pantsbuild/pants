# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple, cast

from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.build_graph.address import Address
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.addressable import Addresses
from pants.engine.legacy.graph import (
    Owners,
    OwnersRequest,
    _DependentGraph,
    target_types_from_build_file_aliases,
)
from pants.engine.mapper import AddressMapper
from pants.engine.parser import HydratedStruct
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.goal.workspace import ScmWorkspace
from pants.option.option_value_container import OptionValueContainer
from pants.scm.scm import Scm
from pants.subsystem.subsystem import Subsystem


class IncludeDependeesOption(Enum):
    NONE = "none"
    DIRECT = "direct"
    TRANSITIVE = "transitive"


@dataclass(frozen=True)
class ChangedRequest:
    sources: Tuple[str, ...]
    include_dependees: IncludeDependeesOption


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
    owners = await Get[Owners](OwnersRequest(sources=changed_request.sources))

    # If the ChangedRequest does not require dependees, then we're done.
    if changed_request.include_dependees == IncludeDependeesOption.NONE:
        return ChangedAddresses(owners.addresses)

    # Otherwise: find dependees.
    all_addresses = await Get[Addresses](AddressSpecs((DescendantAddresses(""),)))
    all_structs = [
        s.value for s in await MultiGet(Get[HydratedStruct](Address, a) for a in all_addresses)
    ]

    bfa = build_configuration.registered_aliases()
    graph = _DependentGraph.from_iterable(
        target_types_from_build_file_aliases(bfa), address_mapper, all_structs
    )
    if changed_request.include_dependees == IncludeDependeesOption.DIRECT:
        return ChangedAddresses(Addresses(graph.dependents_of_addresses(owners.addresses)))
    return ChangedAddresses(Addresses(graph.transitive_dependents_of_addresses(owners.addresses)))


@dataclass(frozen=True)
class ChangedOptions:
    """A wrapper for the options from the `Changed` Subsystem.

    This is necessary because parsing of these options happens before conventional subsystems are
    configured, so the normal mechanisms like `subsystem_rule` would not work properly.
    """

    changes_since: Optional[str]
    diffspec: Optional[str]
    include_dependees: IncludeDependeesOption
    fast: bool

    @classmethod
    def from_options(cls, options: OptionValueContainer) -> "ChangedOptions":
        return cls(options.changes_since, options.diffspec, options.include_dependees, options.fast)

    def is_actionable(self) -> bool:
        return bool(self.changes_since or self.diffspec)

    def changed_files(self, *, scm: Scm) -> List[str]:
        """Determines the files changed according to SCM/workspace and options."""
        workspace = ScmWorkspace(scm)
        if self.diffspec:
            return cast(List[str], workspace.changes_in(self.diffspec))

        changes_since = self.changes_since or scm.current_rev_identifier
        return cast(List[str], workspace.touched_files(changes_since))


class Changed(Subsystem):
    """A subsystem for global `changed` functionality.

    This supports the `--changed-*` argument target root replacements, e.g. `./pants --changed-
    parent=HEAD~3 list`.
    """

    options_scope = "changed"

    @classmethod
    def register_options(cls, register):
        register(
            "--changes-since",
            "--parent",
            "--since",
            type=str,
            default=None,
            help="Calculate changes since this tree-ish/scm ref (defaults to current HEAD/tip).",
        )
        register(
            "--diffspec",
            type=str,
            default=None,
            help="Calculate changes contained within given scm spec (commit range/sha/ref/etc).",
        )
        register(
            "--include-dependees",
            type=IncludeDependeesOption,
            default=IncludeDependeesOption.NONE,
            help="Include direct or transitive dependees of changed targets.",
        )
        register(
            "--fast",
            type=bool,
            default=False,
            help="Stop searching for owners once a source is mapped to at least one owning target.",
        )


def rules():
    return [
        find_owners,
        RootRule(ChangedRequest),
    ]
