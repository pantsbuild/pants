# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.javascript.subsystems import nodejs_tool
from pants.backend.javascript.subsystems.nodejs_tool import NodeJSToolRequest
from pants.backend.openapi.subsystems.redocly import Redocly
from pants.backend.openapi.target_types import (
    OpenApiBundleDummySourceField,
    OpenApiBundleSourceRootField,
    OpenApiDocumentField,
    OpenApiSourceField,
)
from pants.core.target_types import ResourceSourceField
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.internals.native_engine import AddPrefix, Digest, MergeDigests, Snapshot
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    GeneratedSources,
    GenerateSourcesRequest,
    Target,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


class GenerateOpenApiBundleRequest(GenerateSourcesRequest):
    input = OpenApiBundleDummySourceField
    output = ResourceSourceField


@dataclass(frozen=True)
class _BundleOpenApiDocument:
    target: Target
    bundle_source_root: str | None


@rule
async def generate_openapi_bundle_sources(
    request: GenerateOpenApiBundleRequest,
) -> GeneratedSources:
    bundle_source_root = request.protocol_target[OpenApiBundleSourceRootField].value
    openapi_document_targets = await Get(
        Targets, DependenciesRequest(request.protocol_target[Dependencies])
    )
    bundled_documents_digests = await MultiGet(
        Get(Digest, _BundleOpenApiDocument(tgt, bundle_source_root))
        for tgt in openapi_document_targets
        if tgt.has_field(OpenApiDocumentField)
    )
    snapshot = await Get(Snapshot, MergeDigests(bundled_documents_digests))
    return GeneratedSources(snapshot)


@rule
async def bundle_openapi_document(request: _BundleOpenApiDocument, redocly: Redocly) -> Digest:
    transitive_targets = await Get(
        TransitiveTargets, TransitiveTargetsRequest([request.target.address])
    )

    source_root_request = Get(
        SourceRoot,
        SourceRootRequest,
        SourceRootRequest(PurePath(request.bundle_source_root))
        if request.bundle_source_root
        else SourceRootRequest.for_target(request.target),
    )

    target_stripped_sources_request = Get(
        StrippedSourceFiles, SourceFilesRequest([request.target[OpenApiDocumentField]])
    )
    all_stripped_sources_request = Get(
        StrippedSourceFiles,
        SourceFilesRequest(
            tgt[OpenApiSourceField]
            for tgt in transitive_targets.closure
            if tgt.has_field(OpenApiSourceField)
        ),
    )

    source_root, target_stripped_sources, all_stripped_sources = await MultiGet(
        source_root_request,
        target_stripped_sources_request,
        all_stripped_sources_request,
    )

    result = await Get(
        ProcessResult,
        NodeJSToolRequest,
        redocly.request(
            args=(
                "bundle",
                target_stripped_sources.snapshot.files[0],
                "-o",
                target_stripped_sources.snapshot.files[0],
            ),
            input_digest=all_stripped_sources.snapshot.digest,
            output_files=(target_stripped_sources.snapshot.files[0],),
            description=f"Run redocly on {pluralize(len(target_stripped_sources.snapshot.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )

    source_root_restored = (
        await Get(Digest, AddPrefix(result.output_digest, source_root.path))
        if source_root.path != "."
        else result.output_digest
    )
    return source_root_restored


def rules():
    return (
        *collect_rules(),
        *nodejs_tool.rules(),
        UnionRule(GenerateSourcesRequest, GenerateOpenApiBundleRequest),
    )
