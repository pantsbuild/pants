# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.codegen.thrift.apache.java import subsystem
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
    GeneratedSources,
    GenerateSourcesRequest,
    InjectDependenciesRequest,
    InjectedDependencies,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference import artifact_mapper
from pants.jvm.dependency_inference.artifact_mapper import (
    AllJvmArtifactTargets,
    MissingJvmArtifacts,
    UnversionedCoordinate,
    find_jvm_artifacts_or_raise,
)
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField, PrefixedJvmJdkField, PrefixedJvmResolveField
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap


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


class InjectApacheThriftJavaDependencies(InjectDependenciesRequest):
    inject_for = ThriftDependenciesField


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
    try:
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
        )
        return ApacheThriftJavaRuntimeForResolve(addresses)
    except MissingJvmArtifacts:
        raise MissingApacheThriftJavaRuntimeInResolveError(
            request.resolve_name,
        )


@rule
async def inject_apache_thrift_java_dependencies(
    request: InjectApacheThriftJavaDependencies, jvm: JvmSubsystem
) -> InjectedDependencies:
    wrapped_target = await Get(
        WrappedTarget,
        WrappedTargetRequest(
            request.dependencies_field.address, description_of_origin="<infallible>"
        ),
    )
    target = wrapped_target.target

    if not target.has_field(JvmResolveField):
        return InjectedDependencies()
    resolve = target[JvmResolveField].normalized_value(jvm)

    dependencies_info = await Get(
        ApacheThriftJavaRuntimeForResolve, ApacheThriftJavaRuntimeForResolveRequest(resolve)
    )
    return InjectedDependencies(dependencies_info.addresses)


class MissingApacheThriftJavaRuntimeInResolveError(ValueError):
    def __init__(self, resolve_name: str) -> None:
        super().__init__(
            softwrap(
                f"""
                The JVM resolve `{resolve_name}` does not contain a requirement for the Apache Thrift
                runtime. Since at least one JVM target type in this repository consumes a
                `protobuf_sources` target in this resolve, the resolve must contain a `jvm_artifact`
                target for the Apache Thrift runtime.

                Please add the following `jvm_artifact` target somewhere in the repository and re-run
                `{bin_name()} generate-lockfiles --resolve={resolve_name}`:
                    jvm_artifact(
                        name="{_LIBTHRIFT_GROUP}_{_LIBTHRIFT_ARTIFACT}",
                        group="{_LIBTHRIFT_GROUP}",
                        artifact="{_LIBTHRIFT_ARTIFACT}",
                        version="<your chosen version>",
                        resolve="{resolve_name}",
                    )
                """
            )
        )


def rules():
    return (
        *collect_rules(),
        *subsystem.rules(),
        UnionRule(GenerateSourcesRequest, GenerateJavaFromThriftRequest),
        UnionRule(InjectDependenciesRequest, InjectApacheThriftJavaDependencies),
        ThriftSourceTarget.register_plugin_field(PrefixedJvmJdkField),
        ThriftSourcesGeneratorTarget.register_plugin_field(PrefixedJvmJdkField),
        ThriftSourceTarget.register_plugin_field(PrefixedJvmResolveField),
        ThriftSourcesGeneratorTarget.register_plugin_field(PrefixedJvmResolveField),
        # Rules needed to avoid rule graph errors.
        *artifact_mapper.rules(),
    )
