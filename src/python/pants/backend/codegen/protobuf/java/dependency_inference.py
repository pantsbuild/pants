# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from typing import FrozenSet

from pants.backend.codegen.protobuf.target_types import ProtobufDependenciesField
from pants.build_graph.address import Address
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, InferDependenciesRequest, InferredDependencies
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference.artifact_mapper import (
    AllJvmArtifactTargets,
    UnversionedCoordinate,
    find_jvm_artifacts_or_raise,
)
from pants.jvm.dependency_inference.artifact_mapper import rules as artifact_mapper_rules
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField

_PROTOBUF_JAVA_RUNTIME_GROUP = "com.google.protobuf"
_PROTOBUF_JAVA_RUNTIME_ARTIFACT = "protobuf-java"


@dataclass(frozen=True)
class ProtobufJavaRuntimeDependencyInferenceFiedSet(FieldSet):
    required_fields = (
        ProtobufDependenciesField,
        JvmResolveField,
    )

    dependencies: ProtobufDependenciesField
    resolve: JvmResolveField


class InferProtobufJavaRuntimeDependencyRequest(InferDependenciesRequest):
    infer_from = ProtobufJavaRuntimeDependencyInferenceFiedSet


@dataclass(frozen=True)
class ProtobufJavaRuntimeForResolveRequest:
    resolve_name: str


@dataclass(frozen=True)
class ProtobufJavaRuntimeForResolve:
    addresses: FrozenSet[Address]


@rule
async def resolve_protobuf_java_runtime_for_resolve(
    jvm_artifact_targets: AllJvmArtifactTargets,
    jvm: JvmSubsystem,
    request: ProtobufJavaRuntimeForResolveRequest,
) -> ProtobufJavaRuntimeForResolve:
    addresses = find_jvm_artifacts_or_raise(
        required_coordinates=[
            UnversionedCoordinate(
                group=_PROTOBUF_JAVA_RUNTIME_GROUP,
                artifact=_PROTOBUF_JAVA_RUNTIME_ARTIFACT,
            )
        ],
        resolve=request.resolve_name,
        jvm_artifact_targets=jvm_artifact_targets,
        jvm=jvm,
        subsystem="the Protobuf Java runtime",
        target_type="protobuf_sources",
    )
    return ProtobufJavaRuntimeForResolve(addresses)


@rule
async def infer_protobuf_java_runtime_dependency(
    request: InferProtobufJavaRuntimeDependencyRequest,
    jvm: JvmSubsystem,
) -> InferredDependencies:
    resolve = request.field_set.resolve.normalized_value(jvm)

    protobuf_java_runtime_target_info = await Get(
        ProtobufJavaRuntimeForResolve, ProtobufJavaRuntimeForResolveRequest(resolve)
    )

    return InferredDependencies(protobuf_java_runtime_target_info.addresses)


def rules():
    return (
        *collect_rules(),
        *artifact_mapper_rules(),
        UnionRule(InferDependenciesRequest, InferProtobufJavaRuntimeDependencyRequest),
    )
