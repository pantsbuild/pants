# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from collections import defaultdict
from typing import DefaultDict, Mapping, Tuple

from pants.backend.codegen.soap.java.extra_fields import JavaPackageField
from pants.backend.codegen.soap.target_types import AllWsdlTargets
from pants.engine.addresses import Address
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference.artifact_mapper import MutableTrieNode
from pants.jvm.dependency_inference.symbol_mapper import FirstPartyMappingRequest, SymbolMap
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.util.ordered_set import OrderedSet

_ResolveName = str


class FirstPartyWsdlJaxWsTargetsMappingRequest(FirstPartyMappingRequest):
    pass


@rule
async def map_first_party_wsdl_jaxws_targets_to_symbols(
    _: FirstPartyWsdlJaxWsTargetsMappingRequest, wsdl_targets: AllWsdlTargets, jvm: JvmSubsystem
) -> SymbolMap:
    package_mapping: DefaultDict[Tuple[_ResolveName, str], OrderedSet[Address]] = defaultdict(
        OrderedSet
    )
    for target in wsdl_targets:
        resolve_name = target[JvmResolveField].normalized_value(jvm)
        package_name = target[JavaPackageField].value

        # TODO If no explicit package name is given, parse the WSDL and derive it from its namespace
        if not package_name:
            continue

        package_mapping[(resolve_name, package_name)].add(target.address)

    symbol_map: Mapping[_ResolveName, MutableTrieNode] = defaultdict(MutableTrieNode)
    for (resolve, package), addresses in package_mapping.items():
        symbol_map[resolve].insert(package, addresses, first_party=True, recursive=True)

    return SymbolMap((resolve, node.frozen()) for resolve, node in symbol_map.items())


def rules():
    return [
        *collect_rules(),
        UnionRule(FirstPartyMappingRequest, FirstPartyWsdlJaxWsTargetsMappingRequest),
    ]
