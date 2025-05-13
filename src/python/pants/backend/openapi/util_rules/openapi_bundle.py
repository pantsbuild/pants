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
from pants.core.util_rules.stripped_source_files import strip_source_roots
from pants.engine.internals.graph import resolve_targets
from pants.engine.internals.graph import transitive_targets as transitive_targets_get
from pants.engine.internals.native_engine import AddPrefix, Digest, MergeDigests
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import add_prefix, digest_to_snapshot
from pants.engine.process import fallible_to_exec_result_or_raise
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    GeneratedSources,
    GenerateSourcesRequest,
    Target,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.source.source_root import SourceRootRequest, get_source_root
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
async def bundle_openapi_document(request: _BundleOpenApiDocument, redocly: Redocly) -> Digest:
    transitive_targets = await transitive_targets_get(
        TransitiveTargetsRequest([request.target.address]), **implicitly()
    )

    source_root_request = get_source_root(
        SourceRootRequest(PurePath(request.bundle_source_root))
        if request.bundle_source_root
        else SourceRootRequest.for_target(request.target)
    )

    target_stripped_sources_request = strip_source_roots(
        **implicitly(SourceFilesRequest([request.target[OpenApiDocumentField]]))
    )
    all_stripped_sources_request = strip_source_roots(
        **implicitly(
            SourceFilesRequest(
                tgt[OpenApiSourceField]
                for tgt in transitive_targets.closure
                if tgt.has_field(OpenApiSourceField)
            )
        )
    )

    source_root, target_stripped_sources, all_stripped_sources = await concurrently(
        source_root_request,
        target_stripped_sources_request,
        all_stripped_sources_request,
    )

    result = await fallible_to_exec_result_or_raise(
        **implicitly(
            {
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
                ): NodeJSToolRequest
            }
        )
    )

    source_root_restored = (
        await add_prefix(AddPrefix(result.output_digest, source_root.path))
        if source_root.path != "."
        else result.output_digest
    )
    return source_root_restored


@rule
async def generate_openapi_bundle_sources(
    request: GenerateOpenApiBundleRequest,
) -> GeneratedSources:
    bundle_source_root = request.protocol_target[OpenApiBundleSourceRootField].value
    openapi_document_targets = await resolve_targets(
        **implicitly(DependenciesRequest(request.protocol_target[Dependencies]))
    )
    bundled_documents_digests = await concurrently(
        bundle_openapi_document(_BundleOpenApiDocument(tgt, bundle_source_root), **implicitly())
        for tgt in openapi_document_targets
        if tgt.has_field(OpenApiDocumentField)
    )
    snapshot = await digest_to_snapshot(**implicitly(MergeDigests(bundled_documents_digests)))
    return GeneratedSources(snapshot)


def rules():
    return (
        *collect_rules(),
        *nodejs_tool.rules(),
        UnionRule(GenerateSourcesRequest, GenerateOpenApiBundleRequest),
    )
