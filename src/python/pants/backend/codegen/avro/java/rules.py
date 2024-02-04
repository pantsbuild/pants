# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable

from pants.backend.codegen.avro.java.subsystem import AvroSubsystem
from pants.backend.codegen.avro.target_types import (
    AvroDependenciesField,
    AvroSourceField,
    AvroSourcesGeneratorTarget,
    AvroSourceTarget,
)
from pants.backend.java.target_types import JavaSourceField
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.build_graph.address import Address
from pants.core.goals.resolve_helpers import GenerateToolLockfileSentinel
from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    DigestSubset,
    Directory,
    GlobExpansionConjunction,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
    Snapshot,
)
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, rule
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
from pants.jvm import jdk_rules
from pants.jvm.dependency_inference import artifact_mapper
from pants.jvm.dependency_inference.artifact_mapper import (
    AllJvmArtifactTargets,
    UnversionedCoordinate,
    find_jvm_artifacts_or_raise,
)
from pants.jvm.jdk_rules import InternalJdk, JvmProcess
from pants.jvm.resolve import jvm_tool
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool, GenerateJvmToolLockfileSentinel
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField, PrefixedJvmJdkField, PrefixedJvmResolveField
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel


class GenerateJavaFromAvroRequest(GenerateSourcesRequest):
    input = AvroSourceField
    output = JavaSourceField


class AvroToolLockfileSentinel(GenerateJvmToolLockfileSentinel):
    resolve_name = AvroSubsystem.options_scope


@dataclass(frozen=True)
class CompileAvroSourceRequest:
    digest: Digest
    path: str


@dataclass(frozen=True)
class CompiledAvroSource:
    output_digest: Digest


@rule(desc="Generate Java from Avro", level=LogLevel.DEBUG)
async def generate_java_from_avro(
    request: GenerateJavaFromAvroRequest,
) -> GeneratedSources:
    sources = await Get(
        HydratedSources, HydrateSourcesRequest(request.protocol_target[AvroSourceField])
    )

    compile_results = await MultiGet(
        Get(CompiledAvroSource, CompileAvroSourceRequest(sources.snapshot.digest, path))
        for path in sources.snapshot.files
    )

    merged_output_digest, source_root = await MultiGet(
        Get(Digest, MergeDigests([r.output_digest for r in compile_results])),
        Get(SourceRoot, SourceRootRequest, SourceRootRequest.for_target(request.protocol_target)),
    )

    source_root_restored = (
        await Get(Snapshot, AddPrefix(merged_output_digest, source_root.path))
        if source_root.path != "."
        else await Get(Snapshot, Digest, merged_output_digest)
    )
    return GeneratedSources(source_root_restored)


@rule
async def compile_avro_source(
    request: CompileAvroSourceRequest,
    jdk: InternalJdk,
    avro_tools: AvroSubsystem,
) -> CompiledAvroSource:
    output_dir = "_generated_files"
    toolcp_relpath = "__toolcp"

    lockfile_request = await Get(GenerateJvmLockfileFromTool, AvroToolLockfileSentinel())
    tool_classpath, subsetted_input_digest, empty_output_dir = await MultiGet(
        Get(ToolClasspath, ToolClasspathRequest(lockfile=lockfile_request)),
        Get(
            Digest,
            DigestSubset(
                request.digest,
                PathGlobs(
                    [request.path],
                    glob_match_error_behavior=GlobMatchErrorBehavior.error,
                    conjunction=GlobExpansionConjunction.all_match,
                    description_of_origin="the Avro source file name",
                ),
            ),
        ),
        Get(Digest, CreateDigest([Directory(output_dir)])),
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            [
                subsetted_input_digest,
                empty_output_dir,
            ]
        ),
    )

    extra_immutable_input_digests = {
        toolcp_relpath: tool_classpath.digest,
    }

    def make_avro_process(
        args: Iterable[str],
        *,
        overridden_input_digest: Digest | None = None,
        overridden_output_dir: str | None = None,
    ) -> JvmProcess:
        return JvmProcess(
            jdk=jdk,
            argv=(
                "org.apache.avro.tool.Main",
                *args,
            ),
            classpath_entries=tool_classpath.classpath_entries(toolcp_relpath),
            input_digest=(
                overridden_input_digest if overridden_input_digest is not None else input_digest
            ),
            extra_jvm_options=avro_tools.jvm_options,
            extra_immutable_input_digests=extra_immutable_input_digests,
            extra_nailgun_keys=extra_immutable_input_digests,
            description="Generating Java sources from Avro source.",
            level=LogLevel.DEBUG,
            output_directories=(overridden_output_dir if overridden_output_dir else output_dir,),
        )

    path = PurePath(request.path)
    if path.suffix == ".avsc":
        result = await Get(
            ProcessResult,
            JvmProcess,
            make_avro_process(["compile", "schema", request.path, output_dir]),
        )
    elif path.suffix == ".avpr":
        result = await Get(
            ProcessResult,
            JvmProcess,
            make_avro_process(["compile", "protocol", request.path, output_dir]),
        )
    elif path.suffix == ".avdl":
        idl_output_dir = "__idl"
        avpr_path = os.path.join(idl_output_dir, str(path.with_suffix(".avpr")))
        idl_output_dir_digest = await Get(
            Digest, CreateDigest([Directory(os.path.dirname(avpr_path))])
        )
        idl_input_digest = await Get(Digest, MergeDigests([input_digest, idl_output_dir_digest]))
        idl_result = await Get(
            ProcessResult,
            JvmProcess,
            make_avro_process(
                ["idl", request.path, avpr_path],
                overridden_input_digest=idl_input_digest,
                overridden_output_dir=idl_output_dir,
            ),
        )
        generated_files_dir = await Get(Digest, CreateDigest([Directory(output_dir)]))
        protocol_input_digest = await Get(
            Digest, MergeDigests([idl_result.output_digest, generated_files_dir])
        )
        result = await Get(
            ProcessResult,
            JvmProcess,
            make_avro_process(
                ["compile", "protocol", avpr_path, output_dir],
                overridden_input_digest=protocol_input_digest,
            ),
        )
    else:
        raise AssertionError(
            f"Avro backend does not support files with extension `{path.suffix}`: {path}"
        )

    normalized_digest = await Get(Digest, RemovePrefix(result.output_digest, output_dir))
    return CompiledAvroSource(normalized_digest)


@rule
def generate_avro_tools_lockfile_request(
    _: AvroToolLockfileSentinel, tool: AvroSubsystem
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool.create(tool)


@dataclass(frozen=True)
class AvroRuntimeDependencyInferenceFieldSet(FieldSet):
    required_fields = (
        AvroDependenciesField,
        JvmResolveField,
    )

    dependencies: AvroDependenciesField
    resolve: JvmResolveField


class InferAvroRuntimeDependencyRequest(InferDependenciesRequest):
    infer_from = AvroRuntimeDependencyInferenceFieldSet


@dataclass(frozen=True)
class ApacheAvroRuntimeForResolveRequest:
    resolve_name: str


@dataclass(frozen=True)
class ApacheAvroRuntimeForResolve:
    addresses: frozenset[Address]


_AVRO_GROUP = "org.apache.avro"


@rule
async def resolve_apache_avro_runtime_for_resolve(
    request: ApacheAvroRuntimeForResolveRequest,
    jvm_artifact_targets: AllJvmArtifactTargets,
    jvm: JvmSubsystem,
) -> ApacheAvroRuntimeForResolve:
    addresses = find_jvm_artifacts_or_raise(
        required_coordinates=[
            UnversionedCoordinate(
                group=_AVRO_GROUP,
                artifact="avro",
            ),
            UnversionedCoordinate(
                group=_AVRO_GROUP,
                artifact="avro-ipc",
            ),
        ],
        resolve=request.resolve_name,
        jvm_artifact_targets=jvm_artifact_targets,
        jvm=jvm,
        subsystem="the Apache Avro runtime",
        target_type="avro_sources",
    )
    return ApacheAvroRuntimeForResolve(addresses)


@rule
async def infer_apache_avro_java_dependencies(
    request: InferAvroRuntimeDependencyRequest, jvm: JvmSubsystem
) -> InferredDependencies:
    resolve = request.field_set.resolve.normalized_value(jvm)

    dependencies_info = await Get(
        ApacheAvroRuntimeForResolve, ApacheAvroRuntimeForResolveRequest(resolve)
    )
    return InferredDependencies(dependencies_info.addresses)


class MissingApacheAvroRuntimeInResolveError(ValueError):
    def __init__(self, resolve_name: str) -> None:
        super().__init__(
            f"The JVM resolve `{resolve_name}` does not contain a requirement for the Apache Avro runtime. "
            "Since at least one JVM target type in this repository consumes a `avro_sources` target "
            "in this resolve, the resolve must contain a `jvm_artifact` target for the Apache Avro runtime.\n\n"
            "Please add the following `jvm_artifact` targets somewhere in the repository and re-run "
            f"`{bin_name()} generate-lockfiles --resolve={resolve_name}`:\n"
            "jvm_artifact(\n"
            f'  name="{_AVRO_GROUP}_avro",\n'
            f'  group="{_AVRO_GROUP}",\n'
            f'  artifact="avro",\n'
            '  version="<your chosen version>",\n'
            f'  resolve="{resolve_name}",\n'
            ")\n\n"
            "jvm_artifact(\n"
            f'  name="{_AVRO_GROUP}_avro",\n'
            f'  group="{_AVRO_GROUP}",\n'
            f'  artifact="avro-ipc",\n'
            '  version="<your chosen version>",\n'
            f'  resolve="{resolve_name}",\n'
            ")"
        )


def rules():
    return (
        *collect_rules(),
        *jvm_tool.rules(),
        *jdk_rules.rules(),
        UnionRule(GenerateSourcesRequest, GenerateJavaFromAvroRequest),
        UnionRule(GenerateToolLockfileSentinel, AvroToolLockfileSentinel),
        UnionRule(InferDependenciesRequest, InferAvroRuntimeDependencyRequest),
        AvroSourceTarget.register_plugin_field(PrefixedJvmJdkField),
        AvroSourcesGeneratorTarget.register_plugin_field(PrefixedJvmJdkField),
        AvroSourceTarget.register_plugin_field(PrefixedJvmResolveField),
        AvroSourcesGeneratorTarget.register_plugin_field(PrefixedJvmResolveField),
        # Needed to avoid rule graph errors (for dependency inference):
        *artifact_mapper.rules(),
    )
