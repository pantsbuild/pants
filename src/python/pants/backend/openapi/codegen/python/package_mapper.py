# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from collections import defaultdict
from typing import DefaultDict, Mapping, Tuple

from pants.backend.openapi.codegen.java.extra_fields import (
    OpenApiJavaModelPackageField,
)
from pants.backend.openapi.codegen.python.extra_fields import OpenApiPythonAdditionalPropertiesField
from pants.backend.openapi.target_types import AllOpenApiDocumentTargets
from pants.backend.python.dependency_inference.module_mapper import (
    FirstPartyPythonMappingImpl,
    FirstPartyPythonTargetsMappingMarker,
)
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonResolveField
from pants.engine.addresses import Address
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference.artifact_mapper import MutableTrieNode
from pants.jvm.dependency_inference.symbol_mapper import FirstPartyMappingRequest, SymbolMap
from pants.util.ordered_set import OrderedSet

_ResolveName = str


class FirstPartyOpenAPIJavaTargetsMappingRequest(FirstPartyMappingRequest):
    pass


_DEFAULT_API_PACKAGE = "org.openapitools.client.api"
_DEFAULT_MODEL_PACKAGE = "org.openapitools.client.model"


@rule
async def map_openapi_documents_to_python_modules(
    all_openapi_document_targets: AllOpenApiDocumentTargets,
    python_setup: PythonSetup,
    _: FirstPartyPythonTargetsMappingMarker,
) -> FirstPartyPythonMappingImpl:
    package_mapping: DefaultDict[Tuple[_ResolveName, str], OrderedSet[Address]] = defaultdict(
        OrderedSet
    )
    for target in all_openapi_document_targets:
        resolve_name = target[PythonResolveField].normalized_value(python_setup)
        package_name = (target[OpenApiPythonAdditionalPropertiesField].value or {}).get(
            "packageName"
        )
        if package_name is None:
            continue

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
