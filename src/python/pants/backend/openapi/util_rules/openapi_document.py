# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pathlib import PurePath

from pants.backend.javascript.subsystems import nodejs_tool
from pants.backend.javascript.subsystems.nodejs_tool import NodeJSToolRequest
from pants.backend.openapi.subsystems.redocly import Redocly
from pants.backend.openapi.target_types import (
    OpenApiDocumentField,
    OpenApiDocumentGeneratorTarget,
    OpenApiDocumentTarget,
    OpenApiSourceField,
)
from pants.core.target_types import ResourceSourceField
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.internals.native_engine import AddPrefix, Digest, Snapshot
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    GeneratedSources,
    GenerateSourcesRequest,
    StringField,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.logging import LogLevel
from pants.util.strutil import help_text, pluralize


class BundleOpenApiDocumentRequest(GenerateSourcesRequest):
    input = OpenApiDocumentField
    output = ResourceSourceField


class BundleSourceRootField(StringField):
    alias = "bundle_source_root"
    help = help_text(
        """
        The source root to bundle OpenAPI documents under.

        If unspecified, the source root the `openapi_documents` is under will be used.
        """
    )


@rule
async def bundle_openapi_document(
    request: BundleOpenApiDocumentRequest, redocly: Redocly
) -> GeneratedSources:
    target = request.protocol_target
    bundle_source_root = request.protocol_target.get(BundleSourceRootField).value
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest([target.address]))
    source_root_request = Get(
        SourceRoot,
        SourceRootRequest,
        SourceRootRequest(PurePath(bundle_source_root))
        if bundle_source_root
        else SourceRootRequest.for_target(request.protocol_target),
    )

    target_stripped_sources_request = Get(
        StrippedSourceFiles, SourceFilesRequest([target[OpenApiDocumentField]])
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
        await Get(Snapshot, AddPrefix(result.output_digest, source_root.path))
        if source_root.path != "."
        else await Get(Snapshot, Digest, result.output_digest)
    )

    return GeneratedSources(source_root_restored)


def rules():
    return (
        *collect_rules(),
        *nodejs_tool.rules(),
        UnionRule(GenerateSourcesRequest, BundleOpenApiDocumentRequest),
        OpenApiDocumentTarget.register_plugin_field(BundleSourceRootField),
        OpenApiDocumentGeneratorTarget.register_plugin_field(BundleSourceRootField),
    )
