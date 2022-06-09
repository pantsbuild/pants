# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from collections import defaultdict
from typing import Mapping

from pants.backend.scala.dependency_inference.scala_parser import ScalaSourceDependencyAnalysis
from pants.backend.scala.target_types import ScalaSourceField
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import AllTargets, Targets
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference import symbol_mapper
from pants.jvm.dependency_inference.artifact_mapper import (
    DEFAULT_SYMBOL_NAMESPACE,
    MutableTrieNode,
    SymbolNamespace,
)
from pants.jvm.dependency_inference.symbol_mapper import FirstPartyMappingRequest, SymbolMap
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.util.logging import LogLevel


# TODO: add third-party targets here? That would allow us to avoid iterating over AllTargets twice.
#  See `backend/python/dependency_inference/module_mapper.py` for an example.
class AllScalaTargets(Targets):
    pass


class FirstPartyScalaTargetsMappingRequest(FirstPartyMappingRequest):
    pass


@rule(desc="Find all Scala targets in project", level=LogLevel.DEBUG)
def find_all_scala_targets(targets: AllTargets) -> AllScalaTargets:
    return AllScalaTargets(tgt for tgt in targets if tgt.has_field(ScalaSourceField))


SCALA_PACKAGE_OBJECT_NAMESPACE: SymbolNamespace = "package object"


def _symbol_namespace(address: Address) -> SymbolNamespace:
    # NB: Although it is not required that `package object`s be declared in files
    # named `package.scala`, it is a very common (and reasonable) convention. Additionally,
    # we could technically mark only symbols which were declared _inside_ a `package object`,
    # rather than using the filename as a heuristic like this.
    if address.is_file_target and address.filename.endswith("package.scala"):
        return SCALA_PACKAGE_OBJECT_NAMESPACE
    else:
        return DEFAULT_SYMBOL_NAMESPACE


@rule(desc="Map all first party Scala targets to their symbols", level=LogLevel.DEBUG)
async def map_first_party_scala_targets_to_symbols(
    _: FirstPartyScalaTargetsMappingRequest,
    scala_targets: AllScalaTargets,
    jvm: JvmSubsystem,
) -> SymbolMap:
    source_analysis = await MultiGet(
        Get(ScalaSourceDependencyAnalysis, SourceFilesRequest([target[ScalaSourceField]]))
        for target in scala_targets
    )
    address_and_analysis = zip(
        [(tgt.address, tgt[JvmResolveField].normalized_value(jvm)) for tgt in scala_targets],
        source_analysis,
    )

    mapping: Mapping[str, MutableTrieNode] = defaultdict(MutableTrieNode)
    for (address, resolve), analysis in address_and_analysis:
        namespace = _symbol_namespace(address)
        for symbol in analysis.provided_symbols:
            mapping[resolve].insert(symbol, [address], first_party=True, namespace=namespace)
        for symbol in analysis.provided_symbols_encoded:
            mapping[resolve].insert(symbol, [address], first_party=True, namespace=namespace)

    return SymbolMap((resolve, node.frozen()) for resolve, node in mapping.items())


def rules():
    return (
        *collect_rules(),
        *symbol_mapper.rules(),
        UnionRule(FirstPartyMappingRequest, FirstPartyScalaTargetsMappingRequest),
    )
