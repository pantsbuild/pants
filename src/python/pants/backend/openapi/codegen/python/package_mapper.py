# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import PurePath
from typing import DefaultDict

from pants.backend.openapi.target_types import AllOpenApiDocumentTargets, OpenApiDocumentField
from pants.backend.python.dependency_inference.module_mapper import (
    FirstPartyPythonMappingImpl,
    FirstPartyPythonMappingImplMarker,
    ModuleProvider,
    ModuleProviderType,
    ResolveName,
    module_from_stripped_path,
)
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonResolveField, PythonSourceField
from pants.core.util_rules.stripped_source_files import StrippedFileName, StrippedFileNameRequest
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import HydratedSources, HydrateSourcesRequest
from pants.engine.unions import UnionRule

logger = logging.getLogger(__name__)


class PythonOpenApiMappingMarker(FirstPartyPythonMappingImplMarker):
    pass


@rule
async def map_openapi_documents_to_python_modules(
    all_openapi_document_targets: AllOpenApiDocumentTargets,
    python_setup: PythonSetup,
    _: PythonOpenApiMappingMarker,
) -> FirstPartyPythonMappingImpl:
    python_sources = await MultiGet(
        Get(
            HydratedSources,
            HydrateSourcesRequest(
                target[OpenApiDocumentField],
                for_sources_types=(PythonSourceField,),
                enable_codegen=True,
            ),
        )
        for target in all_openapi_document_targets
    )

    stripped_file_per_target_sources = await MultiGet(
        MultiGet(
            Get(StrippedFileName, StrippedFileNameRequest(file)) for file in sources.snapshot.files
        )
        for sources in python_sources
    )

    resolves_to_modules_to_providers: DefaultDict[
        ResolveName, DefaultDict[str, list[ModuleProvider]]
    ] = defaultdict(lambda: defaultdict(list))

    for target, files in zip(all_openapi_document_targets, stripped_file_per_target_sources):
        resolve_name = target[PythonResolveField].normalized_value(python_setup)
        provider = ModuleProvider(target.address, ModuleProviderType.IMPL)
        for stripped_file in files:
            stripped_f = PurePath(stripped_file.value)
            module = module_from_stripped_path(stripped_f)
            resolves_to_modules_to_providers[resolve_name][module].append(provider)

    return FirstPartyPythonMappingImpl.create(resolves_to_modules_to_providers)


def rules():
    return [
        *collect_rules(),
        UnionRule(FirstPartyPythonMappingImplMarker, PythonOpenApiMappingMarker),
    ]
