# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import defaultdict
from typing import Mapping

from pants.backend.kotlin.dependency_inference.kotlin_parser import KotlinSourceDependencyAnalysis
from pants.backend.kotlin.target_types import KotlinSourceField
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import AllTargets, Targets
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference.artifact_mapper import MutableTrieNode
from pants.jvm.dependency_inference.symbol_mapper import FirstPartyMappingRequest, SymbolMap
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.util.logging import LogLevel


# TODO: add third-party targets here? That would allow us to avoid iterating over AllTargets twice.
#  See `backend/python/dependency_inference/module_mapper.py` for an example.
class AllKotlinTargets(Targets):
    pass


class FirstPartyKotlinTargetsMappingRequest(FirstPartyMappingRequest):
    pass


@rule(desc="Find all Kotlin targets in project", level=LogLevel.DEBUG)
def find_all_kotlin_targets(targets: AllTargets) -> AllKotlinTargets:
    return AllKotlinTargets(tgt for tgt in targets if tgt.has_field(KotlinSourceField))


@rule(desc="Map all first party Kotlin targets to their symbols", level=LogLevel.DEBUG)
async def map_first_party_kotlin_targets_to_symbols(
    _: FirstPartyKotlinTargetsMappingRequest,
    kotlin_targets: AllKotlinTargets,
    jvm: JvmSubsystem,
) -> SymbolMap:
    source_analysis = await MultiGet(
        Get(KotlinSourceDependencyAnalysis, SourceFilesRequest([target[KotlinSourceField]]))
        for target in kotlin_targets
    )
    address_and_analysis = zip(
        [(tgt.address, tgt[JvmResolveField].normalized_value(jvm)) for tgt in kotlin_targets],
        source_analysis,
    )

    mapping: Mapping[str, MutableTrieNode] = defaultdict(MutableTrieNode)
    for (address, resolve), analysis in address_and_analysis:
        for symbol in analysis.named_declarations:
            mapping[resolve].insert(symbol, [address], first_party=True)

    return SymbolMap((resolve, node.frozen()) for resolve, node in mapping.items())


def rules():
    return (
        *collect_rules(),
        UnionRule(FirstPartyMappingRequest, FirstPartyKotlinTargetsMappingRequest),
    )
