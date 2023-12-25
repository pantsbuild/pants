# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.codegen.protobuf.scala.subsystem import ScalaPBSubsystem
from pants.backend.codegen.protobuf.target_types import ProtobufDependenciesField
from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.build_graph.address import Address
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, InferDependenciesRequest, InferredDependencies
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference.artifact_mapper import (
    AllJvmArtifactTargets,
    find_jvm_artifacts_or_raise,
)
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.jvm.resolve.coordinate import Coordinate

_SCALAPB_RUNTIME_GROUP = "com.thesamet.scalapb"
_SCALAPB_RUNTIME_ARTIFACT = "scalapb-runtime"


@dataclass(frozen=True)
class ScalaPBRuntimeDependencyInferenceFieldSet(FieldSet):
    required_fields = (ProtobufDependenciesField, JvmResolveField)

    dependencies: ProtobufDependenciesField
    resolve: JvmResolveField


class InferScalaPBRuntimeDependencyRequest(InferDependenciesRequest):
    infer_from = ScalaPBRuntimeDependencyInferenceFieldSet


@dataclass(frozen=True)
class ScalaPBRuntimeForResolveRequest:
    resolve_name: str


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

    addresses = find_jvm_artifacts_or_raise(
        required_coordinates=[
            Coordinate(
                group=_SCALAPB_RUNTIME_GROUP,
                artifact=f"{_SCALAPB_RUNTIME_ARTIFACT}_{scala_binary_version}",
                version=version,
            )
        ],
        resolve=request.resolve_name,
        jvm_artifact_targets=jvm_artifact_targets,
        jvm=jvm,
        subsystem="the ScalaPB runtime",
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

    scalapb_runtime_target_info = await Get(
        ScalaPBRuntimeForResolve, ScalaPBRuntimeForResolveRequest(resolve)
    )
    return InferredDependencies(scalapb_runtime_target_info.addresses)


def rules():
    return (
        *collect_rules(),
        UnionRule(InferDependenciesRequest, InferScalaPBRuntimeDependencyRequest),
    )
