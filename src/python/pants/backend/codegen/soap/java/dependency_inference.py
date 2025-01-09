# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet

from pants.backend.codegen.soap.java.jaxws import JaxWsTools
from pants.backend.codegen.soap.target_types import WsdlDependenciesField
from pants.engine.addresses import Address
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import FieldSet, InferDependenciesRequest, InferredDependencies
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference.artifact_mapper import (
    AllJvmArtifactTargets,
    find_jvm_artifacts_or_raise,
)
from pants.jvm.resolve.coordinate import Coordinate
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField

_JAXWS_RUNTIME_GROUP = "com.sun.xml.ws"
_JAXWS_RUNTIME_ARTIFACT = "jaxws-rt"


@dataclass(frozen=True)
class JaxWSRuntimeDependencyInferenceFieldSet(FieldSet):
    required_fields = (WsdlDependenciesField, JvmResolveField)

    resolve: JvmResolveField


class InferJaxWSRuntimeDependenciesRequest(InferDependenciesRequest):
    infer_from = JaxWSRuntimeDependencyInferenceFieldSet


@dataclass(frozen=True)
class JaxWSJavaRuntimeForResolveRequest:
    resolve_name: str


@dataclass(frozen=True)
class JaxWSJavaRuntimeForResolve:
    addresses: FrozenSet[Address]


@rule
async def resolve_jaxws_runtime_for_resolve(
    request: JaxWSJavaRuntimeForResolveRequest,
    jvm_artifact_targets: AllJvmArtifactTargets,
    jvm: JvmSubsystem,
    jaxws: JaxWsTools,
) -> JaxWSJavaRuntimeForResolve:
    addresses = find_jvm_artifacts_or_raise(
        required_coordinates=[
            Coordinate(
                group=_JAXWS_RUNTIME_GROUP,
                artifact=_JAXWS_RUNTIME_ARTIFACT,
                version=jaxws.version,
            )
        ],
        resolve=request.resolve_name,
        jvm_artifact_targets=jvm_artifact_targets,
        jvm=jvm,
        subsystem="the JaxWS runtime",
        target_type="wsdl_sources",
        requirement_source=f"the `[{jaxws.options_scope}].version` option",
    )
    return JaxWSJavaRuntimeForResolve(addresses)


@rule
async def infer_jaxws_runtime_dependency(
    request: InferJaxWSRuntimeDependenciesRequest, jvm: JvmSubsystem
) -> InferredDependencies:
    resolve = request.field_set.resolve.normalized_value(jvm)

    jaxws_resolved_runtime = await Get(
        JaxWSJavaRuntimeForResolve, JaxWSJavaRuntimeForResolveRequest(resolve)
    )
    return InferredDependencies(jaxws_resolved_runtime.addresses)


def rules():
    return [
        *collect_rules(),
        UnionRule(InferDependenciesRequest, InferJaxWSRuntimeDependenciesRequest),
    ]
