# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.java.dependency_inference.package_prefix_tree import PackageRootedDependencyMap
from pants.backend.java.dependency_inference.types import JavaSourceDependencyAnalysis
from pants.backend.java.target_types import JavaSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import AllTargets, Targets
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------------------------
# First-party package mapping
# -----------------------------------------------------------------------------------------------


# TODO: add third-party targets here? That would allow us to avoid iterating over AllTargets twice.
#  See `backend/python/dependency_inference/module_mapper.py` for an example.
class AllJavaTargets(Targets):
    pass


@rule(desc="Find all Java targets in project", level=LogLevel.DEBUG)
def find_all_java_targets(tgts: AllTargets) -> AllJavaTargets:
    return AllJavaTargets(tgt for tgt in tgts if tgt.has_field(JavaSourceField))


@dataclass(frozen=True)
class FirstPartyJavaMappingImpl:
    """A mapping of package names to owning addresses that a specific implementation adds for Java
    import dependency inference."""

    package_rooted_dependency_map: PackageRootedDependencyMap


@union
class FirstPartyJavaMappingImplMarker:
    """An entry point for a specific implementation of mapping package names to owning targets for
    Java import dependency inference.

    All implementations will be merged together.

    The addresses should all be file addresses, rather than BUILD addresses.
    """


@dataclass(frozen=True)
class FirstPartyJavaPackageMapping:
    """A merged mapping of package names to owning addresses."""

    package_rooted_dependency_map: PackageRootedDependencyMap


@rule(level=LogLevel.DEBUG)
async def merge_first_party_module_mappings(
    union_membership: UnionMembership,
) -> FirstPartyJavaPackageMapping:
    all_mappings = await MultiGet(
        Get(
            FirstPartyJavaMappingImpl,
            FirstPartyJavaMappingImplMarker,
            marker_cls(),
        )
        for marker_cls in union_membership.get(FirstPartyJavaMappingImplMarker)
    )

    merged_dep_map = PackageRootedDependencyMap()
    for dep_map in all_mappings:
        merged_dep_map.merge(dep_map.package_rooted_dependency_map)

    return FirstPartyJavaPackageMapping(package_rooted_dependency_map=merged_dep_map)


# This is only used to register our implementation with the plugin hook via unions. Note that we
# implement this like any other plugin implementation so that we can run them all in parallel.
class FirstPartyJavaTargetsMappingMarker(FirstPartyJavaMappingImplMarker):
    pass


@rule(desc="Map all first party Java targets to their packages", level=LogLevel.DEBUG)
async def map_first_party_java_targets_to_symbols(
    _: FirstPartyJavaTargetsMappingMarker, java_targets: AllJavaTargets
) -> FirstPartyJavaMappingImpl:
    source_files = await MultiGet(
        Get(SourceFiles, SourceFilesRequest([target[JavaSourceField]])) for target in java_targets
    )
    source_analysis = await MultiGet(
        Get(JavaSourceDependencyAnalysis, SourceFiles, source_files)
        for source_files in source_files
    )
    address_and_analysis = zip([t.address for t in java_targets], source_analysis)

    dep_map = PackageRootedDependencyMap()
    for address, analysis in address_and_analysis:
        for top_level_type in analysis.top_level_types:
            components = top_level_type.rsplit(".", maxsplit=1)
            if len(components) != 2:
                # A package without a name cannot be imported, and so does not expose any symbols.
                # https://docs.oracle.com/javase/specs/jls/se8/html/jls-7.html#jls-7.4.2
                continue
            package, type_ = components
            dep_map.add_top_level_type(package=package, type_=type_, address=address)

    return FirstPartyJavaMappingImpl(package_rooted_dependency_map=dep_map)


def rules():
    return (
        *collect_rules(),
        UnionRule(FirstPartyJavaMappingImplMarker, FirstPartyJavaTargetsMappingMarker),
    )
