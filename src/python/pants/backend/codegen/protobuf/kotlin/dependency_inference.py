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


@dataclass(frozen=True)
class ProtobufKotlinRuntimeDependencyInferenceFieldSet(FieldSet):
    required_fields = (
        ProtobufDependenciesField,
        JvmResolveField,
    )

    dependencies: ProtobufDependenciesField
    resolve: JvmResolveField


class InferProtobufKotlinRuntimeDependencyRequest(InferDependenciesRequest):
    infer_from = ProtobufKotlinRuntimeDependencyInferenceFieldSet


@dataclass(frozen=True)
class ProtobufKotlinRuntimeForResolveRequest:
    resolve_name: str


@dataclass(frozen=True)
class ProtobufKotlinRuntimeForResolve:
    addresses: FrozenSet[Address]


@rule
async def resolve_protobuf_kotlin_runtime_for_resolve(
    jvm_artifact_targets: AllJvmArtifactTargets,
    jvm: JvmSubsystem,
    request: ProtobufKotlinRuntimeForResolveRequest,
) -> ProtobufKotlinRuntimeForResolve:
    addresses = find_jvm_artifacts_or_raise(
        required_coordinates=[
            UnversionedCoordinate(
                group="com.google.protobuf",
                artifact="protobuf-kotlin",
            )
        ],
        resolve=request.resolve_name,
        jvm_artifact_targets=jvm_artifact_targets,
        jvm=jvm,
        subsystem="the Protobuf Kotlin runtime",
        target_type="protobuf_sources",
    )
    return ProtobufKotlinRuntimeForResolve(addresses)


@rule
async def infer_protobuf_kotlin_runtime_dependency(
    request: InferProtobufKotlinRuntimeDependencyRequest,
    jvm: JvmSubsystem,
) -> InferredDependencies:
    resolve = request.field_set.resolve.normalized_value(jvm)

    protobuf_java_runtime_target_info = await Get(
        ProtobufKotlinRuntimeForResolve, ProtobufKotlinRuntimeForResolveRequest(resolve)
    )

    return InferredDependencies(protobuf_java_runtime_target_info.addresses)


def rules():
    return (
        *collect_rules(),
        *artifact_mapper_rules(),
        UnionRule(InferDependenciesRequest, InferProtobufKotlinRuntimeDependencyRequest),
    )
