# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.helm.codegen.helmdocs.subsystem import HelmDocsSubsystem
from pants.backend.helm.target_types import HelmChartReadmeField, HelmChartSourcesField
from pants.backend.helm.util_rules.sources import HelmChartSourceFiles, HelmChartSourceFilesRequest
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.engine.fs import (
    AddPrefix,
    Digest,
    DigestContents,
    DigestSubset,
    PathGlobs,
    RemovePrefix,
    Snapshot,
)
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import GeneratedSources, GenerateSourcesRequest
from pants.engine.unions import UnionRule
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.logging import LogLevel

_GENERATED_FILE_NAME = "README.md"


class HelmDocsGenerationFailedError(Exception):
    pass


class GenerateHelmDocsRequest(GenerateSourcesRequest):
    input = HelmChartSourcesField
    output = HelmChartReadmeField


@rule(desc="Generate Helm Chart documentation", level=LogLevel.DEBUG)
async def generate_helm_docs(
    request: GenerateHelmDocsRequest, helm_docs: HelmDocsSubsystem
) -> GeneratedSources:
    downloaded_helm_docs, source_files = await MultiGet(
        Get(DownloadedExternalTool, ExternalToolRequest, helm_docs.get_request(Platform.current)),
        Get(
            HelmChartSourceFiles,
            HelmChartSourceFilesRequest,
            HelmChartSourceFilesRequest.create(
                request.protocol_target, generate_docs=False, include_metadata=True
            ),
        ),
    )

    bin_prefix = "__bin"
    immutable_input_digests = {
        bin_prefix: downloaded_helm_docs.digest,
    }

    sources_prefix = "__chart"
    sources_digest = await Get(Digest, AddPrefix(source_files.snapshot.digest, sources_prefix))

    result = await Get(
        ProcessResult,
        Process(
            [
                f"{bin_prefix}/{downloaded_helm_docs.exe}",
                "--chart-search-root",
                sources_prefix,
                "--output-file",
                _GENERATED_FILE_NAME,
            ],
            input_digest=sources_digest,
            immutable_input_digests=immutable_input_digests,
            output_directories=(sources_prefix,),
            description=f"Generate documentation for target: {request.protocol_target.address}",
            level=LogLevel.DEBUG,
        ),
    )

    generated_file = await Get(
        Digest,
        DigestSubset(result.output_digest, PathGlobs([f"{sources_prefix}/{_GENERATED_FILE_NAME}"])),
    )
    generated_file_contents = await Get(DigestContents, Digest, generated_file)
    if len(generated_file_contents) == 0:
        raise HelmDocsGenerationFailedError(
            f"Could not find a generated {_GENERATED_FILE_NAME} file for target: {request.protocol_target.address}"
        )
    if len(generated_file_contents[0].content.decode()) == 0:
        raise HelmDocsGenerationFailedError(
            f"Generated {_GENERATED_FILE_NAME} file had no contents at target: {request.protocol_target.address}"
        )

    source_root_request = SourceRootRequest.for_target(request.protocol_target)
    normalized_digest, source_root = await MultiGet(
        Get(Digest, RemovePrefix(generated_file, sources_prefix)),
        Get(SourceRoot, SourceRootRequest, source_root_request),
    )

    sources_snapshot = (
        await Get(Snapshot, AddPrefix(normalized_digest, source_root.path))
        if source_root.path != "."
        else await Get(Snapshot, Digest, normalized_digest)
    )
    return GeneratedSources(sources_snapshot)


def rules():
    return [*collect_rules(), UnionRule(GenerateSourcesRequest, GenerateHelmDocsRequest)]
