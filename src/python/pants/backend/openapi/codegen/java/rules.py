# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.java.target_types import JavaSourceField
from pants.backend.openapi.codegen.java import extra_fields, symbol_mapper
from pants.backend.openapi.codegen.java.extra_fields import (
    OpenApiJavaApiPackageField,
    OpenApiJavaModelPackageField,
    OpenApiJavaSkipField,
)
from pants.backend.openapi.sample.resources import PETSTORE_SAMPLE_SPEC
from pants.backend.openapi.subsystems.openapi_generator import OpenAPIGenerator
from pants.backend.openapi.target_types import (
    OpenApiDocumentDependenciesField,
    OpenApiDocumentField,
    OpenApiDocumentTarget,
    OpenApiSourceField,
)
from pants.backend.openapi.util_rules import generator_process, pom_parser
from pants.backend.openapi.util_rules.generator_process import OpenAPIGeneratorProcess
from pants.backend.openapi.util_rules.pom_parser import AnalysePomRequest, analyse_pom
from pants.engine.fs import (
    EMPTY_SNAPSHOT,
    AddPrefix,
    CreateDigest,
    Digest,
    DigestSubset,
    Directory,
    FileContent,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
)
from pants.engine.internals.graph import hydrate_sources
from pants.engine.internals.graph import transitive_targets as transitive_targets_get
from pants.engine.intrinsics import (
    create_digest,
    digest_subset_to_digest,
    digest_to_snapshot,
    merge_digests,
    remove_prefix,
)
from pants.engine.process import fallible_to_exec_result_or_raise
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import (
    FieldSet,
    GeneratedSources,
    GenerateSourcesRequest,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference import artifact_mapper
from pants.jvm.dependency_inference.artifact_mapper import (
    AllJvmArtifactTargets,
    find_jvm_artifacts_or_raise,
)
from pants.jvm.resolve.coordinate import Coordinate
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.source.source_root import SourceRootRequest, get_source_root
from pants.util.logging import LogLevel


class GenerateJavaFromOpenAPIRequest(GenerateSourcesRequest):
    input = OpenApiDocumentField
    output = JavaSourceField


@dataclass(frozen=True)
class OpenApiDocumentJavaFieldSet(FieldSet):
    required_fields = (OpenApiDocumentField,)

    source: OpenApiDocumentField
    dependencies: OpenApiDocumentDependenciesField
    api_package: OpenApiJavaApiPackageField
    model_package: OpenApiJavaModelPackageField
    skip: OpenApiJavaSkipField


@dataclass(frozen=True)
class CompileOpenApiIntoJavaRequest:
    input_file: str
    input_digest: Digest
    description: str
    api_package: str | None = None
    model_package: str | None = None


@dataclass(frozen=True)
class CompiledJavaFromOpenApi:
    output_digest: Digest
    runtime_dependencies: tuple[Coordinate, ...]


@rule
async def compile_openapi_into_java(
    request: CompileOpenApiIntoJavaRequest,
) -> CompiledJavaFromOpenApi:
    output_dir = "__gen"
    output_digest = await create_digest(CreateDigest([Directory(output_dir)]))

    merged_digests = await merge_digests(MergeDigests([request.input_digest, output_digest]))

    process = OpenAPIGeneratorProcess(
        generator_name="java",
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
        description=request.description,
        level=LogLevel.DEBUG,
    )

    result = await fallible_to_exec_result_or_raise(
        **implicitly({process: OpenAPIGeneratorProcess})
    )
    normalized_digest = await remove_prefix(RemovePrefix(result.output_digest, output_dir))

    pom_digest, java_sources_digest = await concurrently(
        digest_subset_to_digest(DigestSubset(normalized_digest, PathGlobs(["pom.xml"]))),
        digest_subset_to_digest(
            DigestSubset(normalized_digest, PathGlobs(["src/main/java/**/*.java"]))
        ),
    )

    pom_report, stripped_java_sources_digest = await concurrently(
        analyse_pom(AnalysePomRequest(pom_digest)),
        remove_prefix(RemovePrefix(java_sources_digest, "src/main/java")),
    )

    return CompiledJavaFromOpenApi(
        output_digest=stripped_java_sources_digest, runtime_dependencies=pom_report.dependencies
    )


@rule
async def generate_java_from_openapi(request: GenerateJavaFromOpenAPIRequest) -> GeneratedSources:
    field_set = OpenApiDocumentJavaFieldSet.create(request.protocol_target)
    if field_set.skip.value:
        return GeneratedSources(EMPTY_SNAPSHOT)

    document_sources, transitive_targets = await concurrently(
        hydrate_sources(HydrateSourcesRequest(field_set.source), **implicitly()),
        transitive_targets_get(TransitiveTargetsRequest([field_set.address]), **implicitly()),
    )

    document_dependencies = await concurrently(
        hydrate_sources(HydrateSourcesRequest(tgt[OpenApiSourceField]), **implicitly())
        for tgt in transitive_targets.dependencies
        if tgt.has_field(OpenApiSourceField)
    )

    input_digest = await merge_digests(
        MergeDigests(
            [
                document_sources.snapshot.digest,
                *[dependency.snapshot.digest for dependency in document_dependencies],
            ]
        )
    )

    compiled_sources = await concurrently(
        compile_openapi_into_java(
            CompileOpenApiIntoJavaRequest(
                file,
                input_digest=input_digest,
                description=f"Generating Java sources from OpenAPI definition {field_set.address}",
                api_package=field_set.api_package.value,
                model_package=field_set.model_package.value,
            )
        )
        for file in document_sources.snapshot.files
    )

    output_digest, source_root = await concurrently(
        merge_digests(MergeDigests([sources.output_digest for sources in compiled_sources])),
        get_source_root(SourceRootRequest.for_target(request.protocol_target)),
    )

    source_root_restored = (
        await digest_to_snapshot(**implicitly(AddPrefix(output_digest, source_root.path)))
        if source_root.path != "."
        else await digest_to_snapshot(output_digest)
    )
    return GeneratedSources(source_root_restored)


@dataclass(frozen=True)
class OpenApiDocumentJavaRuntimeInferenceFieldSet(FieldSet):
    required_fields = (OpenApiDocumentDependenciesField, JvmResolveField)

    dependencies: OpenApiDocumentDependenciesField
    resolve: JvmResolveField
    skip: OpenApiJavaSkipField


class InferOpenApiJavaRuntimeDependencyRequest(InferDependenciesRequest):
    infer_from = OpenApiDocumentJavaRuntimeInferenceFieldSet


@rule
async def infer_openapi_java_dependencies(
    request: InferOpenApiJavaRuntimeDependencyRequest,
    jvm: JvmSubsystem,
    jvm_artifact_targets: AllJvmArtifactTargets,
    openapi_generator: OpenAPIGenerator,
) -> InferredDependencies:
    if request.field_set.skip.value:
        return InferredDependencies([])

    resolve = request.field_set.resolve.normalized_value(jvm)

    # Because the runtime dependencies are the same regardless of the source being compiled
    # we use a sample OpenAPI spec to find out what are the runtime dependencies
    # for the given resolve and prevent creating a cycle in our rule engine.
    sample_spec_name = "__sample_spec.yaml"
    sample_source_digest = await create_digest(
        CreateDigest(
            [FileContent(path=sample_spec_name, content=PETSTORE_SAMPLE_SPEC.encode("utf-8"))]
        )
    )
    compiled_sources = await compile_openapi_into_java(
        CompileOpenApiIntoJavaRequest(
            input_file=sample_spec_name,
            input_digest=sample_source_digest,
            description=f"Inferring Java runtime dependencies for OpenAPI v{openapi_generator.version}",
        )
    )

    addresses = find_jvm_artifacts_or_raise(
        required_coordinates=compiled_sources.runtime_dependencies,
        resolve=resolve,
        jvm_artifact_targets=jvm_artifact_targets,
        jvm=jvm,
        subsystem="the OpenAPI Java runtime",
        target_type=OpenApiDocumentTarget.alias,
    )
    return InferredDependencies(addresses)


def rules():
    return [
        *collect_rules(),
        *extra_fields.rules(),
        *generator_process.rules(),
        *artifact_mapper.rules(),
        *pom_parser.rules(),
        *symbol_mapper.rules(),
        UnionRule(GenerateSourcesRequest, GenerateJavaFromOpenAPIRequest),
        UnionRule(InferDependenciesRequest, InferOpenApiJavaRuntimeDependencyRequest),
    ]
