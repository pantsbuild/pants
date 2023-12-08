# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations
from collections import defaultdict
from typing import DefaultDict, Mapping
from pants.backend.codegen.thrift.target_types import AllThriftTargets, ThriftSourceField
from pants.backend.codegen.thrift.thrift_parser import ParsedThrift, ParsedThriftRequest
from pants.engine.rules import rule, MultiGet, Get, collect_rules
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference.artifact_mapper import MutableTrieNode

from pants.jvm.dependency_inference.symbol_mapper import FirstPartyMappingRequest, SymbolMap
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.util.ordered_set import OrderedSet
from pants.engine.addresses import Address

_ResolveName = str

class FirstPartyThriftJavaTargetsMappingRequest(FirstPartyMappingRequest):
  pass

@rule
async def map_first_party_thrif_java_targets_to_symbols(_: FirstPartyThriftJavaTargetsMappingRequest, thrift_targets: AllThriftTargets, jvm: JvmSubsystem) -> SymbolMap:
  parsed_thrift_sources = await MultiGet(
    Get(ParsedThrift, ParsedThriftRequest(tgt[ThriftSourceField]))
    for tgt in thrift_targets
  )

  package_symbols: DefaultDict[tuple[_ResolveName, str], OrderedSet[Address]] = defaultdict(
      OrderedSet
  )
  for target, parsed_thrift in zip(thrift_targets, parsed_thrift_sources):
    package_name = parsed_thrift.namespaces.get("java")
    if not package_name:
      continue

    resolve = target[JvmResolveField].normalized_value(jvm)
    package_symbols[(resolve, package_name)].add(target.address)

  mapping: Mapping[str, MutableTrieNode] = defaultdict(MutableTrieNode)
  for (resolve, package_name), addresses in package_symbols.items():
      mapping[resolve].insert(package_name, addresses, first_party=True, recursive=True)

  return SymbolMap((resolve, node.frozen()) for resolve, node in mapping.items())


def rules():
  return [
    *collect_rules(),
    UnionRule(FirstPartyMappingRequest, FirstPartyThriftJavaTargetsMappingRequest)
  ]
