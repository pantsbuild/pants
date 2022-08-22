# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.codegen.thrift.scrooge.rules import (
    GeneratedScroogeThriftSources,
    GenerateScroogeThriftSourcesRequest,
)
from pants.backend.codegen.thrift.target_types import (
    ThriftDependenciesField,
    ThriftSourceField,
    ThriftSourcesGeneratorTarget,
    ThriftSourceTarget,
)
from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.backend.scala.target_types import ScalaSourceField
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


class GenerateScalaFromThriftRequest(GenerateSourcesRequest):
    input = ThriftSourceField
    output = ScalaSourceField


@dataclass(frozen=True)
class ScroogeThriftScalaDependenciesInferenceFieldSet(FieldSet):
    required_fields = (
        ThriftDependenciesField,
        JvmResolveField,
    )

    dependencies: ThriftDependenciesField
    resolve: JvmResolveField


class InferScroogeThriftScalaDependencies(InferDependenciesRequest):
    infer_from = ScroogeThriftScalaDependenciesInferenceFieldSet


@rule(desc="Generate Scala from Thrift with Scrooge", level=LogLevel.DEBUG)
async def generate_scala_from_thrift_with_scrooge(
    request: GenerateScalaFromThriftRequest,
) -> GeneratedSources:
    result = await Get(
        GeneratedScroogeThriftSources,
        GenerateScroogeThriftSourcesRequest(
            thrift_source_field=request.protocol_target[ThriftSourceField],
            lang_id="scala",
            lang_name="Scala",
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
class ScroogeThriftScalaRuntimeForResolveRequest:
    resolve_name: str


@dataclass(frozen=True)
class ScroogeThriftScalaRuntimeForResolve:
    addresses: frozenset[Address]


@rule
async def resolve_scrooge_thrift_scala_runtime_for_resolve(
    request: ScroogeThriftScalaRuntimeForResolveRequest,
    jvm_artifact_targets: AllJvmArtifactTargets,
    jvm: JvmSubsystem,
    scala_subsystem: ScalaSubsystem,
) -> ScroogeThriftScalaRuntimeForResolve:
    scala_version = scala_subsystem.version_for_resolve(request.resolve_name)
    scala_binary_version, _, _ = scala_version.rpartition(".")
    addresses = find_jvm_artifacts_or_raise(
        required_coordinates=[
            UnversionedCoordinate(
                group="org.apache.thrift",
                artifact="libthrift",
            ),
            UnversionedCoordinate(
                group="com.twitter",
                artifact=f"scrooge-core_{scala_binary_version}",
            ),
        ],
        resolve=request.resolve_name,
        jvm_artifact_targets=jvm_artifact_targets,
        jvm=jvm,
        subsystem="the Scrooge Scala Thrift runtime",
        target_type="thrift_sources",
    )
    return ScroogeThriftScalaRuntimeForResolve(addresses)


@rule
async def inject_scrooge_thrift_scala_dependencies(
    request: InferScroogeThriftScalaDependencies, jvm: JvmSubsystem
) -> InferredDependencies:
    resolve = request.field_set.resolve.normalized_value(jvm)
    dependencies_info = await Get(
        ScroogeThriftScalaRuntimeForResolve, ScroogeThriftScalaRuntimeForResolveRequest(resolve)
    )
    return InferredDependencies(dependencies_info.addresses)


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateSourcesRequest, GenerateScalaFromThriftRequest),
        UnionRule(InferDependenciesRequest, InferScroogeThriftScalaDependencies),
        ThriftSourceTarget.register_plugin_field(PrefixedJvmJdkField),
        ThriftSourcesGeneratorTarget.register_plugin_field(PrefixedJvmJdkField),
        ThriftSourceTarget.register_plugin_field(PrefixedJvmResolveField),
        ThriftSourcesGeneratorTarget.register_plugin_field(PrefixedJvmResolveField),
        # Rules to avoid rule graph errors.
        *artifact_mapper.rules(),
    )
