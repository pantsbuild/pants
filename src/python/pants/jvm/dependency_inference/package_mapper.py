# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionMembership, union
from pants.jvm.dependency_inference.package_prefix_tree import PackageRootedDependencyMap
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------------------------
# First-party package mapping
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FirstPartyMappingImpl:
    """A mapping of JVM package names to owning addresses that a specific implementation adds."""

    package_rooted_dependency_map: PackageRootedDependencyMap


@union
class FirstPartyMappingRequest:
    """An entry point for a specific implementation of mapping JVM package names to owning targets.

    All implementations will be merged together.

    The addresses should all be file addresses, rather than BUILD addresses.
    """


@dataclass(frozen=True)
class FirstPartyPackageMapping:
    """A merged mapping of package names to owning addresses."""

    package_rooted_dependency_map: PackageRootedDependencyMap


@rule(level=LogLevel.DEBUG)
async def merge_first_party_module_mappings(
    union_membership: UnionMembership,
) -> FirstPartyPackageMapping:
    all_mappings = await MultiGet(
        Get(
            FirstPartyMappingImpl,
            FirstPartyMappingRequest,
            marker_cls(),
        )
        for marker_cls in union_membership.get(FirstPartyMappingRequest)
    )

    merged_dep_map = PackageRootedDependencyMap()
    for dep_map in all_mappings:
        merged_dep_map.merge(dep_map.package_rooted_dependency_map)

    return FirstPartyPackageMapping(package_rooted_dependency_map=merged_dep_map)


def rules():
    return collect_rules()
