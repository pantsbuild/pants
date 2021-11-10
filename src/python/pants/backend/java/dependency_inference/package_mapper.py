# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

from pants.backend.java.dependency_inference.types import JavaSourceDependencyAnalysis
from pants.backend.java.target_types import JavaSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import AllTargets, Targets
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference.package_mapper import (
    FirstPartyMappingImpl,
    FirstPartyMappingRequest,
)
from pants.jvm.dependency_inference.package_prefix_tree import PackageRootedDependencyMap
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class AllJavaTargets(Targets):
    pass


@rule(desc="Find all Java targets in project", level=LogLevel.DEBUG)
def find_all_java_targets(tgts: AllTargets) -> AllJavaTargets:
    return AllJavaTargets(tgt for tgt in tgts if tgt.has_field(JavaSourceField))


class FirstPartyJavaTargetsMappingRequest(FirstPartyMappingRequest):
    pass


@rule(desc="Map all first party Java targets to their packages", level=LogLevel.DEBUG)
async def map_first_party_java_targets_to_symbols(
    _: FirstPartyJavaTargetsMappingRequest, java_targets: AllJavaTargets
) -> FirstPartyMappingImpl:
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
            dep_map.add_top_level_type(top_level_type, address=address)

    return FirstPartyMappingImpl(package_rooted_dependency_map=dep_map)


def rules():
    return (
        *collect_rules(),
        UnionRule(FirstPartyMappingRequest, FirstPartyJavaTargetsMappingRequest),
    )
