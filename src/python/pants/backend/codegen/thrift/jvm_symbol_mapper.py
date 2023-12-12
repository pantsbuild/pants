# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict, Mapping

from pants.backend.codegen.thrift.target_types import AllThriftTargets, ThriftSourceField
from pants.backend.codegen.thrift.thrift_parser import ParsedThrift, ParsedThriftRequest
from pants.engine.addresses import Address
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.jvm.dependency_inference.artifact_mapper import MutableTrieNode
from pants.jvm.dependency_inference.symbol_mapper import SymbolMap
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.util.ordered_set import OrderedSet

_ResolveName = str


@dataclass(frozen=True)
class FirstPartyJvmMappingRequest:
    lang_ids: tuple[str, ...]
    extra_namespace_directives: tuple[str, ...] = ()


@rule
async def map_first_party_thirft_targets_to_jvm_symbols(
    request: FirstPartyJvmMappingRequest, thrift_targets: AllThriftTargets, jvm: JvmSubsystem
) -> SymbolMap:
    jvm_thrift_targets = [tgt for tgt in thrift_targets if tgt.has_field(JvmResolveField)]

    parsed_thrift_sources = await MultiGet(
        Get(
            ParsedThrift,
            ParsedThriftRequest(
                sources_field=tgt[ThriftSourceField],
                extra_namespace_directives=request.extra_namespace_directives,
            ),
        )
        for tgt in jvm_thrift_targets
    )

    package_symbols: DefaultDict[tuple[_ResolveName, str], OrderedSet[Address]] = defaultdict(
        OrderedSet
    )
    for target, parsed_thrift in zip(jvm_thrift_targets, parsed_thrift_sources):
        for lang_id in request.lang_ids:
            package_name = parsed_thrift.namespaces.get(lang_id)
            if not package_name:
                continue

            resolve = target[JvmResolveField].normalized_value(jvm)
            package_symbols[(resolve, package_name)].add(target.address)

    mapping: Mapping[str, MutableTrieNode] = defaultdict(MutableTrieNode)
    for (resolve, package_name), addresses in package_symbols.items():
        mapping[resolve].insert(package_name, addresses, first_party=True, recursive=True)

    return SymbolMap((resolve, node.frozen()) for resolve, node in mapping.items())


def rules():
    return collect_rules()
