# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Tuple

from packaging.utils import canonicalize_name as canonicalize_project_name

from pants.backend.codegen.utils import MissingPythonCodegenRuntimeLibrary
from pants.backend.openapi.codegen.python.extra_fields import (
    OpenApiPythonAdditionalPropertiesField,
    OpenApiPythonGeneratorNameField,
    OpenApiPythonSkipField,
)
from pants.backend.openapi.sample.resources import PETSTORE_SAMPLE_SPEC
from pants.backend.openapi.subsystems.openapi_generator import OpenAPIGenerator
from pants.backend.openapi.target_types import (
    OpenApiDocumentDependenciesField,
    OpenApiDocumentField,
)
from pants.backend.openapi.util_rules.generator_process import OpenAPIGeneratorProcess
from pants.backend.python.dependency_inference.module_mapper import AllPythonTargets
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    PrefixedPythonResolveField,
    PythonRequirementResolveField,
    PythonRequirementsField,
    PythonSourceField,
)
from pants.engine.fs import (
    EMPTY_SNAPSHOT,
    AddPrefix,
    CreateDigest,
    Digest,
    DigestContents,
    DigestSubset,
    Directory,
    FileContent,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
    Snapshot,
)
from pants.engine.internals.native_engine import Address
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    FieldSet,
    GeneratedSources,
    GenerateSourcesRequest,
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
)
from pants.engine.unions import UnionRule
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.pip_requirement import PipRequirement
from pants.util.requirements import parse_requirements_file
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class GeneratePythonFromOpenAPIRequest(GenerateSourcesRequest):
    input = OpenApiDocumentField
    output = PythonSourceField


@dataclass(frozen=True)
class OpenApiDocumentPythonFieldSet(FieldSet):
    required_fields = (OpenApiDocumentField,)

    source: OpenApiDocumentField
    dependencies: OpenApiDocumentDependenciesField
    generator_name: OpenApiPythonGeneratorNameField
    additional_properties: OpenApiPythonAdditionalPropertiesField
    skip: OpenApiPythonSkipField


@dataclass(frozen=True)
class CompileOpenApiIntoPythonRequest:
    input_file: str
    input_digest: Digest
    description: str
    generator_name: str
    additional_properties: FrozenDict[str, str] | None = None


@dataclass(frozen=True)
class CompiledPythonFromOpenApi:
    output_digest: Digest
    runtime_dependencies: tuple[PipRequirement, ...]


@rule
async def compile_openapi_into_python(
    request: CompileOpenApiIntoPythonRequest,
) -> CompiledPythonFromOpenApi:
    output_dir = "__gen"
    output_digest = await Get(Digest, CreateDigest([Directory(output_dir)]))

    merged_digests = await Get(Digest, MergeDigests([request.input_digest, output_digest]))

    additional_properties: Iterable[str] = (
        itertools.chain(
            *[
                ("--additional-properties", f"{k}={v}")
                for k, v in request.additional_properties.items()
            ]
        )
        if request.additional_properties
        else ()
    )

    process = OpenAPIGeneratorProcess(
        generator_name=request.generator_name,
        argv=[
            *additional_properties,
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

    result = await Get(ProcessResult, OpenAPIGeneratorProcess, process)
    normalized_digest = await Get(Digest, RemovePrefix(result.output_digest, output_dir))

    requirements_digest, python_sources_digest = await MultiGet(
        Get(Digest, DigestSubset(normalized_digest, PathGlobs(["requirements.txt"]))),
        Get(Digest, DigestSubset(normalized_digest, PathGlobs(["**/*.py"]))),
    )
    requirements_contents = await Get(DigestContents, Digest, requirements_digest)
    runtime_dependencies: Tuple[PipRequirement, ...] = ()
    if len(requirements_contents) > 0:
        file = requirements_contents[0]
        runtime_dependencies = tuple(
            parse_requirements_file(
                file.content.decode("utf-8"),
                rel_path=file.path,
            )
        )

    return CompiledPythonFromOpenApi(
        output_digest=python_sources_digest,
        runtime_dependencies=runtime_dependencies,
    )


@rule
async def generate_python_from_openapi(
    request: GeneratePythonFromOpenAPIRequest,
) -> GeneratedSources:
    field_set = OpenApiDocumentPythonFieldSet.create(request.protocol_target)
    if field_set.skip.value:
        return GeneratedSources(EMPTY_SNAPSHOT)

    (document_sources,) = await MultiGet(
        (Get(HydratedSources, HydrateSourcesRequest(field_set.source)),)
        # Get(TransitiveTargets, TransitiveTargetsRequest([field_set.address])),
    )

    document_dependencies = []
    # await MultiGet(
    #     Get(HydratedSources, HydrateSourcesRequest(tgt[OpenApiSourceField]))
    #     for tgt in transitive_targets.dependencies
    #     if tgt.has_field(OpenApiSourceField)
    # )

    input_digest = await Get(
        Digest,
        MergeDigests(
            [
                document_sources.snapshot.digest,
                *[dependency.snapshot.digest for dependency in document_dependencies],
            ]
        ),
    )

    gets = []
    for file in document_sources.snapshot.files:
        generator_name = field_set.generator_name.value
        if generator_name is None:
            raise ValueError(
                f"Field `{OpenApiPythonGeneratorNameField.alias}` is required for target {field_set.address}"
            )

        gets.append(
            Get(
                CompiledPythonFromOpenApi,
                CompileOpenApiIntoPythonRequest(
                    file,
                    input_digest=input_digest,
                    description=f"Generating Python sources from OpenAPI definition {field_set.address}",
                    generator_name=generator_name,
                    additional_properties=field_set.additional_properties.value,
                ),
            )
        )

    compiled_sources = await MultiGet(gets)

    logger.info("digests: %s", [sources.output_digest for sources in compiled_sources])
    output_digest, source_root = await MultiGet(
        Get(Digest, MergeDigests([sources.output_digest for sources in compiled_sources])),
        Get(SourceRoot, SourceRootRequest, SourceRootRequest.for_target(request.protocol_target)),
    )

    source_root_restored = (
        await Get(Snapshot, AddPrefix(output_digest, source_root.path))
        if source_root.path != "."
        else await Get(Snapshot, Digest, output_digest)
    )
    return GeneratedSources(source_root_restored)


@dataclass(frozen=True)
class OpenApiDocumentPythonRuntimeInferenceFieldSet(FieldSet):
    required_fields = (OpenApiDocumentDependenciesField, PrefixedPythonResolveField)

    dependencies: OpenApiDocumentDependenciesField
    python_resolve: PrefixedPythonResolveField
    generator_name: OpenApiPythonGeneratorNameField
    additional_properties: OpenApiPythonAdditionalPropertiesField
    skip: OpenApiPythonSkipField


class InferOpenApiPythonRuntimeDependencyRequest(InferDependenciesRequest):
    infer_from = OpenApiDocumentPythonRuntimeInferenceFieldSet


@dataclass(frozen=True)
class PythonRequirements:
    resolves_to_requirements_to_addresses: FrozenDict[str, FrozenDict[str, Address]]


@rule
async def get_python_requirements(
    python_targets: AllPythonTargets,
    python_setup: PythonSetup,
) -> PythonRequirements:
    result: defaultdict[str, dict[str, Address]] = defaultdict(dict)
    for target in python_targets.third_party:
        for python_requirement in target[PythonRequirementsField].value:
            project_name = canonicalize_project_name(python_requirement.project_name)
            resolve = target[PythonRequirementResolveField].normalized_value(python_setup)
            result[resolve][project_name] = target.address

    return PythonRequirements(
        resolves_to_requirements_to_addresses=FrozenDict(
            (
                resolve,
                FrozenDict(
                    (requirements, addresses)
                    for requirements, addresses in requirements_to_addresses.items()
                ),
            )
            for resolve, requirements_to_addresses in result.items()
        ),
    )


@rule
async def infer_openapi_python_dependencies(
    request: InferOpenApiPythonRuntimeDependencyRequest,
    python_setup: PythonSetup,
    openapi_generator: OpenAPIGenerator,
    python_requirements: PythonRequirements,
) -> InferredDependencies:
    if request.field_set.skip.value:
        return InferredDependencies([])

    resolve = request.field_set.python_resolve.normalized_value(python_setup)

    # Because the runtime dependencies are the same regardless of the source being compiled
    # we use a sample OpenAPI spec to find out what are the runtime dependencies
    # for the given resolve and prevent creating a cycle in our rule engine.
    sample_spec_name = "__sample_spec.yaml"
    sample_source_digest = await Get(
        Digest,
        CreateDigest(
            [FileContent(path=sample_spec_name, content=PETSTORE_SAMPLE_SPEC.encode("utf-8"))]
        ),
    )
    compiled_sources = await Get(
        CompiledPythonFromOpenApi,
        CompileOpenApiIntoPythonRequest(
            input_file=sample_spec_name,
            input_digest=sample_source_digest,
            description=f"Inferring Python runtime dependencies for OpenAPI v{openapi_generator.version}",
            generator_name=request.field_set.generator_name.value,
            additional_properties=request.field_set.additional_properties.value,
        ),
    )

    logger.info("Looking for thirdparty dependencies: %s", compiled_sources.runtime_dependencies)

    requirements_to_addresses = python_requirements.resolves_to_requirements_to_addresses[resolve]

    addresses, missing_requirements = [], []
    for runtime_dependency in compiled_sources.runtime_dependencies:
        project_name = runtime_dependency.project_name
        address = requirements_to_addresses.get(project_name)
        if address is not None:
            addresses.append(address)
        else:
            missing_requirements.append(project_name)

    if missing_requirements:
        for_resolve_str = f" for the resolve '{resolve}'" if python_setup.enable_resolves else ""
        missing = ", ".join(f"`{project_name}`" for project_name in missing_requirements)
        raise MissingPythonCodegenRuntimeLibrary(
            softwrap(
                f"""
                No `python_requirement` target was found with the packages {missing}
                in your project{for_resolve_str}, so the Python code generated from the target
                {request.field_set.address} will not work properly.
                """
            )
        )

    return InferredDependencies(addresses)


def rules():
    return [
        *collect_rules(),
        UnionRule(GenerateSourcesRequest, GeneratePythonFromOpenAPIRequest),
        UnionRule(InferDependenciesRequest, InferOpenApiPythonRuntimeDependencyRequest),
    ]
