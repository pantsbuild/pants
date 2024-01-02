# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from collections import defaultdict
from typing import DefaultDict, Mapping, Tuple

from pants.backend.openapi.codegen.java.extra_fields import (
    OpenApiJavaApiPackageField,
    OpenApiJavaModelPackageField,
)
from pants.backend.openapi.target_types import AllOpenApiDocumentTargets
from pants.engine.addresses import Address
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference.artifact_mapper import MutableTrieNode
from pants.jvm.dependency_inference.symbol_mapper import FirstPartyMappingRequest, SymbolMap
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.util.ordered_set import OrderedSet

_ResolveName = str


class FirstPartyOpenAPIJavaTargetsMappingRequest(FirstPartyMappingRequest):
    pass


_DEFAULT_API_PACKAGE = "org.openapitools.client.api"
_DEFAULT_MODEL_PACKAGE = "org.openapitools.client.model"


@rule
async def map_first_party_openapi_java_targets_to_symbols(
    _: FirstPartyOpenAPIJavaTargetsMappingRequest,
    all_openapi_document_targets: AllOpenApiDocumentTargets,
    jvm: JvmSubsystem,
) -> SymbolMap:
    package_mapping: DefaultDict[Tuple[_ResolveName, str], OrderedSet[Address]] = defaultdict(
        OrderedSet
    )
    for target in all_openapi_document_targets:
        resolve_name = target[JvmResolveField].normalized_value(jvm)
        api_package = target[OpenApiJavaApiPackageField].value or _DEFAULT_API_PACKAGE
        model_package = target[OpenApiJavaModelPackageField].value or _DEFAULT_MODEL_PACKAGE

        package_mapping[(resolve_name, api_package)].add(target.address)
        package_mapping[(resolve_name, model_package)].add(target.address)

    symbol_map: Mapping[_ResolveName, MutableTrieNode] = defaultdict(MutableTrieNode)
    for (resolve, package), addresses in package_mapping.items():
        symbol_map[resolve].insert(package, addresses, first_party=True, recursive=True)

    return SymbolMap((resolve, node.frozen()) for resolve, node in symbol_map.items())


def rules():
    return [
        *collect_rules(),
        UnionRule(FirstPartyMappingRequest, FirstPartyOpenAPIJavaTargetsMappingRequest),
    ]
