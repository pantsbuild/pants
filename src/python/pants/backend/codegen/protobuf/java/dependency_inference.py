# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from typing import FrozenSet

from pants.backend.codegen.protobuf.target_types import ProtobufDependenciesField
from pants.build_graph.address import Address
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    InjectDependenciesRequest,
    InjectedDependencies,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference.artifact_mapper import (
    AllJvmArtifactTargets,
    ConflictingJvmArtifactVersion,
    MissingJvmArtifacts,
    UnversionedCoordinate,
    find_jvm_artifacts_or_raise,
)
from pants.jvm.dependency_inference.artifact_mapper import rules as artifact_mapper_rules
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.util.docutil import bin_name

_PROTOBUF_JAVA_RUNTIME_GROUP = "com.google.protobuf"
_PROTOBUF_JAVA_RUNTIME_ARTIFACT = "protobuf-java"


class InjectProtobufJavaRuntimeDependencyRequest(InjectDependenciesRequest):
    inject_for = ProtobufDependenciesField


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

    try:
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
        )
        return ProtobufJavaRuntimeForResolve(addresses)
    except (MissingJvmArtifacts, ConflictingJvmArtifactVersion):
        raise MissingProtobufJavaRuntimeInResolveError(request.resolve_name)


@rule
async def inject_protobuf_java_runtime_dependency(
    request: InjectProtobufJavaRuntimeDependencyRequest,
    jvm: JvmSubsystem,
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

    protobuf_java_runtime_target_info = await Get(
        ProtobufJavaRuntimeForResolve, ProtobufJavaRuntimeForResolveRequest(resolve)
    )

    return InjectedDependencies(protobuf_java_runtime_target_info.addresses)


class MissingProtobufJavaRuntimeInResolveError(ValueError):
    def __init__(self, resolve_name: str) -> None:
        super().__init__(
            f"The JVM resolve `{resolve_name}` does not contain a requirement for the protobuf-java "
            "runtime. Since at least one JVM target type in this repository consumes a "
            "`protobuf_sources` target in this resolve, the resolve must contain a `jvm_artifact` "
            "target for the `protobuf-java` runtime.\n\n Please add the following `jvm_artifact` "
            f"target somewhere in the repository and re-run `{bin_name()} generate-lockfiles "
            f"--resolve={resolve_name}`:\n"
            "jvm_artifact(\n"
            f'  name="{_PROTOBUF_JAVA_RUNTIME_GROUP}_{_PROTOBUF_JAVA_RUNTIME_ARTIFACT}",\n'
            f'  group="{_PROTOBUF_JAVA_RUNTIME_GROUP}",\n',
            f'  artifact="{_PROTOBUF_JAVA_RUNTIME_ARTIFACT}",\n',
            '  version="<your preferred runtime version>",\n',
            f'  resolve="{resolve_name}",\n',
            ")",
        )


def rules():
    return (
        *collect_rules(),
        *artifact_mapper_rules(),
        UnionRule(InjectDependenciesRequest, InjectProtobufJavaRuntimeDependencyRequest),
    )
