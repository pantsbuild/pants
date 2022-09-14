# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.java.target_types import JavaSourceField
from pants.backend.openapi.codegen.java import extra_fields
from pants.backend.openapi.codegen.java.extra_fields import (
    OpenApiJavaApiPackageField,
    OpenApiJavaCodegenSkipField,
    OpenApiJavaModelPackageField,
)
from pants.backend.openapi.target_types import OpenApiSourceField
from pants.backend.openapi.util_rules import generator_process
from pants.backend.openapi.util_rules.generator_process import (
    OpenAPIGeneratorProcess,
    OpenAPIGeneratorType,
)
from pants.build_graph.address import Address
from pants.engine.fs import (
    EMPTY_SNAPSHOT,
    AddPrefix,
    CreateDigest,
    Digest,
    DigestSubset,
    Directory,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
    Snapshot,
)
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    GeneratedSources,
    GenerateSourcesRequest,
    HydratedSources,
    HydrateSourcesRequest,
)
from pants.engine.unions import UnionRule
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.logging import LogLevel


class GenerateJavaFromOpenAPIRequest(GenerateSourcesRequest):
    input = OpenApiSourceField
    output = JavaSourceField


@dataclass(frozen=True)
class CompileOpenApiIntoJavaRequest:
    address: Address
    input_file: str
    digest: Digest
    api_package: str | None
    model_package: str | None


@dataclass(frozen=True)
class CompiledJavaFromOpenApi:
    output_digest: Digest


@rule
async def compile_openapi_into_java(
    request: CompileOpenApiIntoJavaRequest,
) -> CompiledJavaFromOpenApi:
    output_dir = "__gen"
    output_digest = await Get(Digest, CreateDigest([Directory(output_dir)]))

    merged_digests = await Get(Digest, MergeDigests([request.digest, output_digest]))

    process = OpenAPIGeneratorProcess(
        generator_type=OpenAPIGeneratorType.JAVA,
        argv=[
            *(
                ("--additional-properties", f"apiPackage={request.api_package}")
                if request.api_package
                else ()
            ),
            *(
                ("--additional-properties", f"modelPackage={request.model_package}")
                if request.model_package
                else ()
            ),
            "-i",
            request.input_file,
            "-o",
            output_dir,
        ],
        input_digest=merged_digests,
        output_directories=(output_dir,),
        description=f"Generating Java sources from OpenAPI definition {request.address}",
        level=LogLevel.DEBUG,
    )

    result = await Get(ProcessResult, OpenAPIGeneratorProcess, process)
    normalized_digest = await Get(Digest, RemovePrefix(result.output_digest, output_dir))
    java_sources_digest = await Get(
        Digest, DigestSubset(normalized_digest, PathGlobs(["src/main/java/**/*.java"]))
    )
    stripped_java_sources_digest = await Get(
        Digest, RemovePrefix(java_sources_digest, "src/main/java")
    )

    return CompiledJavaFromOpenApi(stripped_java_sources_digest)


@rule
async def generate_java_from_openapi(request: GenerateJavaFromOpenAPIRequest) -> GeneratedSources:
    if request.protocol_target[OpenApiJavaCodegenSkipField].value:
        return GeneratedSources(EMPTY_SNAPSHOT)

    sources = await Get(
        HydratedSources, HydrateSourcesRequest(request.protocol_target[OpenApiSourceField])
    )

    compiled_sources = await MultiGet(
        Get(
            CompiledJavaFromOpenApi,
            CompileOpenApiIntoJavaRequest(
                request.protocol_target.address,
                input_file,
                sources.snapshot.digest,
                api_package=request.protocol_target[OpenApiJavaApiPackageField].value,
                model_package=request.protocol_target[OpenApiJavaModelPackageField].value,
            ),
        )
        for input_file in sources.snapshot.files
    )

    merged_output_digests, source_root = await MultiGet(
        Get(Digest, MergeDigests([sources.output_digest for sources in compiled_sources])),
        Get(SourceRoot, SourceRootRequest, SourceRootRequest.for_target(request.protocol_target)),
    )

    source_root_restored = (
        await Get(Snapshot, AddPrefix(merged_output_digests, source_root.path))
        if source_root.path != "."
        else await Get(Snapshot, Digest, merged_output_digests)
    )
    return GeneratedSources(source_root_restored)


def rules():
    return [
        *collect_rules(),
        *extra_fields.rules(),
        *generator_process.rules(),
        UnionRule(GenerateSourcesRequest, GenerateJavaFromOpenAPIRequest),
    ]
