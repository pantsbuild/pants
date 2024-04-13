# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.codegen.thrift.apache.java import subsystem, symbol_mapper
from pants.backend.codegen.thrift.apache.java.subsystem import ApacheThriftJavaSubsystem
from pants.backend.codegen.thrift.apache.rules import (
    GeneratedThriftSources,
    GenerateThriftSourcesRequest,
)
from pants.backend.codegen.thrift.target_types import (
    ThriftDependenciesField,
    ThriftSourceField,
    ThriftSourcesGeneratorTarget,
    ThriftSourceTarget,
)
from pants.backend.java.target_types import JavaSourceField
from pants.build_graph.address import Address
from pants.engine.fs import AddPrefix, Digest, Snapshot
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    FieldSet,
    GeneratedSources,
    GenerateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
)
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference import artifact_mapper
from pants.jvm.dependency_inference.artifact_mapper import (
    AllJvmArtifactTargets,
    UnversionedCoordinate,
    find_jvm_artifacts_or_raise,
)
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField, PrefixedJvmJdkField, PrefixedJvmResolveField
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.logging import LogLevel


class GenerateJavaFromThriftRequest(GenerateSourcesRequest):
    input = ThriftSourceField
    output = JavaSourceField


@rule(desc="Generate Java from Thrift", level=LogLevel.DEBUG)
async def generate_java_from_thrift(
    request: GenerateJavaFromThriftRequest,
    thrift_java: ApacheThriftJavaSubsystem,
) -> GeneratedSources:
    result = await Get(
        GeneratedThriftSources,
        GenerateThriftSourcesRequest(
            thrift_source_field=request.protocol_target[ThriftSourceField],
            lang_id="java",
            lang_options=thrift_java.gen_options,
            lang_name="Java",
        ),
    )

    source_root = await Get(
        SourceRoot, SourceRootRequest, SourceRootRequest.for_target(request.protocol_target)
    )

    source_root_restored = (
        await Get(Snapshot, AddPrefix(result.snapshot.digest, source_root.path))
        if source_root.path != "."
        else await Get(Snapshot, Digest, result.snapshot.digest)
    )
    return GeneratedSources(source_root_restored)


@dataclass(frozen=True)
class ApacheThriftJavaDependenciesInferenceFieldSet(FieldSet):
    required_fields = (ThriftDependenciesField, JvmResolveField)

    dependencies: ThriftDependenciesField
    resolve: JvmResolveField


class InferApacheThriftJavaDependencies(InferDependenciesRequest):
    infer_from = ApacheThriftJavaDependenciesInferenceFieldSet


@dataclass(frozen=True)
class ApacheThriftJavaRuntimeForResolveRequest:
    resolve_name: str


@dataclass(frozen=True)
class ApacheThriftJavaRuntimeForResolve:
    addresses: frozenset[Address]


_LIBTHRIFT_GROUP = "org.apache.thrift"
_LIBTHRIFT_ARTIFACT = "libthrift"


@rule
async def resolve_apache_thrift_java_runtime_for_resolve(
    request: ApacheThriftJavaRuntimeForResolveRequest,
    jvm_artifact_targets: AllJvmArtifactTargets,
    jvm: JvmSubsystem,
) -> ApacheThriftJavaRuntimeForResolve:
    addresses = find_jvm_artifacts_or_raise(
        required_coordinates=[
            UnversionedCoordinate(
                group=_LIBTHRIFT_GROUP,
                artifact=_LIBTHRIFT_ARTIFACT,
            )
        ],
        resolve=request.resolve_name,
        jvm_artifact_targets=jvm_artifact_targets,
        jvm=jvm,
        subsystem="the Apache Thrift runtime",
        target_type="protobuf_sources",
    )
    return ApacheThriftJavaRuntimeForResolve(addresses)


@rule
async def infer_apache_thrift_java_dependencies(
    request: InferApacheThriftJavaDependencies, jvm: JvmSubsystem
) -> InferredDependencies:
    resolve = request.field_set.resolve.normalized_value(jvm)

    dependencies_info = await Get(
        ApacheThriftJavaRuntimeForResolve, ApacheThriftJavaRuntimeForResolveRequest(resolve)
    )
    return InferredDependencies(dependencies_info.addresses)


def rules():
    return (
        *collect_rules(),
        *subsystem.rules(),
        *symbol_mapper.rules(),
        UnionRule(GenerateSourcesRequest, GenerateJavaFromThriftRequest),
        UnionRule(InferDependenciesRequest, InferApacheThriftJavaDependencies),
        ThriftSourceTarget.register_plugin_field(PrefixedJvmJdkField),
        ThriftSourcesGeneratorTarget.register_plugin_field(PrefixedJvmJdkField),
        ThriftSourceTarget.register_plugin_field(PrefixedJvmResolveField),
        ThriftSourcesGeneratorTarget.register_plugin_field(PrefixedJvmResolveField),
        # Rules needed to avoid rule graph errors.
        *artifact_mapper.rules(),
    )
