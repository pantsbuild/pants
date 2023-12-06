# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
import re
from collections import defaultdict
from typing import DefaultDict, Mapping

from pants.backend.codegen.protobuf.target_types import AllProtobufTargets, ProtobufSourceField
from pants.engine.addresses import Address
from pants.engine.fs import Digest, DigestContents, FileContent
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import HydratedSources, HydrateSourcesRequest
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference import symbol_mapper
from pants.jvm.dependency_inference.artifact_mapper import MutableTrieNode
from pants.jvm.dependency_inference.symbol_mapper import FirstPartyMappingRequest, SymbolMap
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.util.ordered_set import OrderedSet

_ResolveName = str


class FirstPartyProtobufJavaTargetsMappingRequest(FirstPartyMappingRequest):
    pass


# Determine generated Java/Scala package name
# * https://grpc.io/docs/languages/java/generated-code
def _determing_class_name(file: FileContent) -> str:
    base_name, _, _ = os.path.basename(file.path).partition(".")
    package_definition = _parse_package_definition(file.content)
    return f"{package_definition}.{base_name.upper()}" if package_definition else base_name.upper()


_QUOTE_CHAR = r"(?:'|\")"
_JAVA_PACKAGE_OPTION_RE = re.compile(
    rf"^\s*option\s+java_package\s+=\s+{_QUOTE_CHAR}(.+){_QUOTE_CHAR};"
)
_PACKAGE_RE = re.compile(r"^\s*package\s+(.+);")


def _parse_package_definition(content_raw: bytes) -> str | None:
    content = content_raw.decode()
    for line in content.splitlines():
        m = _JAVA_PACKAGE_OPTION_RE.match(line)
        if m:
            return m.group(1)
        m = _PACKAGE_RE.match(line)
        if m:
            return m.group(1)
    return None


@rule
async def map_first_party_protobuf_scala_targets_to_symbols(
    _: FirstPartyProtobufJavaTargetsMappingRequest,
    all_protobuf_targets: AllProtobufTargets,
    jvm: JvmSubsystem,
) -> SymbolMap:
    sources = await MultiGet(
        Get(
            HydratedSources,
            HydrateSourcesRequest(
                tgt[ProtobufSourceField],
                for_sources_types=(ProtobufSourceField,),
                enable_codegen=True,
            ),
        )
        for tgt in all_protobuf_targets
    )

    all_contents = await MultiGet(
        Get(DigestContents, Digest, source.snapshot.digest) for source in sources
    )

    class_symbols: DefaultDict[tuple[_ResolveName, str], OrderedSet[Address]] = defaultdict(
        OrderedSet
    )
    for tgt, contents in zip(all_protobuf_targets, all_contents):
        if not contents:
            continue
        if len(contents) > 1:
            raise AssertionError(
                f"Protobuf target `{tgt.address}` mapped to more than one source file."
            )

        resolve = tgt[JvmResolveField].normalized_value(jvm)
        class_name = _determing_class_name(contents[0])
        class_symbols[(resolve, class_name)].add(tgt.address)

    mapping: Mapping[str, MutableTrieNode] = defaultdict(MutableTrieNode)
    for (resolve, class_name), addresses in class_symbols.items():
        mapping[resolve].insert(class_name, addresses, first_party=True, recursive=True)

    return SymbolMap((resolve, node.frozen()) for resolve, node in mapping.items())


def rules():
    return [
        *collect_rules(),
        *symbol_mapper.rules(),
        UnionRule(FirstPartyMappingRequest, FirstPartyProtobufJavaTargetsMappingRequest),
    ]
