# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.codegen.protobuf.scala.subsystem import ScalaPBSubsystem
from pants.backend.codegen.protobuf.target_types import (
    ProtobufDependenciesField,
    ProtobufGrpcToggleField,
)
from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.build_graph.address import Address
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import FieldSet, InferDependenciesRequest, InferredDependencies
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference.artifact_mapper import (
    AllJvmArtifactTargets,
    UnversionedCoordinate,
    find_jvm_artifacts_or_raise,
)
from pants.jvm.resolve.coordinate import Coordinate
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField

_SCALAPB_RUNTIME_GROUP = "com.thesamet.scalapb"
_SCALAPB_RUNTIME_ARTIFACT = "scalapb-runtime"
_SCALAPB_RUNTIME_GRPC_ARTIFACT = "scalapb-runtime-grpc"


@dataclass(frozen=True)
class ScalaPBRuntimeDependencyInferenceFieldSet(FieldSet):
    required_fields = (
        ProtobufDependenciesField,
        JvmResolveField,
        ProtobufGrpcToggleField,
    )

    dependencies: ProtobufDependenciesField
    resolve: JvmResolveField
    grpc: ProtobufGrpcToggleField


class InferScalaPBRuntimeDependencyRequest(InferDependenciesRequest):
    infer_from = ScalaPBRuntimeDependencyInferenceFieldSet


@dataclass(frozen=True)
class ScalaPBRuntimeForResolveRequest:
    resolve_name: str
    grpc: bool = False


@dataclass(frozen=True)
class ScalaPBRuntimeForResolve:
    addresses: frozenset[Address]


@rule
async def resolve_scalapb_runtime_for_resolve(
    request: ScalaPBRuntimeForResolveRequest,
    jvm_artifact_targets: AllJvmArtifactTargets,
    jvm: JvmSubsystem,
    scala_subsystem: ScalaSubsystem,
    scalapb: ScalaPBSubsystem,
) -> ScalaPBRuntimeForResolve:
    scala_version = scala_subsystem.version_for_resolve(request.resolve_name)
    scala_binary_version = scala_version.binary
    version = scalapb.version

    artifact = _SCALAPB_RUNTIME_GRPC_ARTIFACT if request.grpc else _SCALAPB_RUNTIME_ARTIFACT
    subsystem = "the ScalaPB gRPC runtime" if request.grpc else "the ScalaPB runtime"

    required_coordinates: list[Coordinate | UnversionedCoordinate] = [
        Coordinate(
            group=_SCALAPB_RUNTIME_GROUP,
            artifact=f"{artifact}_{scala_binary_version}",
            version=version,
        )
    ]
    if request.grpc:
        # The generated `*Grpc.scala` stubs directly extend `io.grpc.stub.AbstractStub` and
        # reference other `io.grpc` (grpc-api) types, so `grpc-stub` must be resolvable as its
        # own classpath entry: Coursier's resolution of `scalapb-runtime-grpc` alone does not
        # transitively pull in `grpc-api`. Its version isn't controlled by `[scalapb].version`,
        # so match on group/artifact only.
        required_coordinates.append(UnversionedCoordinate(group="io.grpc", artifact="grpc-stub"))

    addresses = find_jvm_artifacts_or_raise(
        required_coordinates=required_coordinates,
        resolve=request.resolve_name,
        jvm_artifact_targets=jvm_artifact_targets,
        jvm=jvm,
        subsystem=subsystem,
        target_type="protobuf_sources",
        requirement_source="the `[scalapb].version` option",
    )
    return ScalaPBRuntimeForResolve(addresses)


@rule
async def infer_scalapb_runtime_dependency(
    request: InferScalaPBRuntimeDependencyRequest,
    jvm: JvmSubsystem,
) -> InferredDependencies:
    resolve = request.field_set.resolve.normalized_value(jvm)

    scalapb_runtime_target_info = await resolve_scalapb_runtime_for_resolve(
        ScalaPBRuntimeForResolveRequest(resolve), **implicitly()
    )
    addresses: set[Address] = set(scalapb_runtime_target_info.addresses)

    if request.field_set.grpc.value:
        grpc_runtime_info = await resolve_scalapb_runtime_for_resolve(
            ScalaPBRuntimeForResolveRequest(resolve, grpc=True), **implicitly()
        )
        addresses.update(grpc_runtime_info.addresses)

    return InferredDependencies(frozenset(addresses))


def rules():
    return (
        *collect_rules(),
        UnionRule(InferDependenciesRequest, InferScalaPBRuntimeDependencyRequest),
    )
