# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.java.dependency_inference.package_prefix_tree import (
    CodeProvence,
    PackageRootedDependencyMap,
)
from pants.backend.java.dependency_inference.types import JavaSourceDependencyAnalysis
from pants.backend.java.target_types import CodeProvenceField, JavaSourceField
from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Target, Targets
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------------------------
# First-party package mapping
# -----------------------------------------------------------------------------------------------


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


@rule(desc="Creating map of first party Java targets to Java packages", level=LogLevel.DEBUG)
async def map_first_party_java_targets_to_symbols(
    _: FirstPartyJavaTargetsMappingMarker,
) -> FirstPartyJavaMappingImpl:
    def get_code_provence(tgt: Target) -> CodeProvence:
        if not tgt.has_field(CodeProvenceField):
            return CodeProvence.NON_TEST
        cp_str = tgt[CodeProvenceField].value
        return CodeProvence.from_str(cp_str)

    all_expanded_targets = await Get(Targets, AddressSpecs([DescendantAddresses("")]))
    java_targets = tuple(tgt for tgt in all_expanded_targets if tgt.has_field(JavaSourceField))
    source_files = await MultiGet(
        Get(SourceFiles, SourceFilesRequest([target[JavaSourceField]])) for target in java_targets
    )
    source_analysis = await MultiGet(
        Get(JavaSourceDependencyAnalysis, SourceFiles, source_files)
        for source_files in source_files
    )
    address_and_analysis = zip(
        [(t.address, get_code_provence(t)) for t in java_targets], source_analysis
    )
    dep_map = PackageRootedDependencyMap()
    for (address, cp), analysis in address_and_analysis:
        for top_level_type in analysis.top_level_types:
            package, type_ = top_level_type.rsplit(".", maxsplit=1)
            dep_map.add_top_level_type(
                package=package, type_=type_, address=address, code_provence=cp
            )

    return FirstPartyJavaMappingImpl(package_rooted_dependency_map=dep_map)


def rules():
    return (
        *collect_rules(),
        UnionRule(FirstPartyJavaMappingImplMarker, FirstPartyJavaTargetsMappingMarker),
    )
