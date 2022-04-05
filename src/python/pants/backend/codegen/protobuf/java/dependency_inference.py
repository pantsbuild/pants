# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass

from pants.backend.codegen.protobuf.target_types import ProtobufDependenciesField
from pants.build_graph.address import Address
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import InjectDependenciesRequest, InjectedDependencies, WrappedTarget
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference.artifact_mapper import AllJvmArtifactTargets
from pants.jvm.resolve.common import ArtifactRequirement
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
    address: Address


@rule
async def resolve_protobuf_java_runtime_for_resolve(
    jvm_artifact_targets: AllJvmArtifactTargets,
    jvm: JvmSubsystem,
    request: ProtobufJavaRuntimeForResolveRequest,
) -> ProtobufJavaRuntimeForResolve:

    for tgt in jvm_artifact_targets:
        if tgt[JvmResolveField].normalized_value(jvm) != request.resolve_name:
            continue

        artifact = ArtifactRequirement.from_jvm_artifact_target(tgt)
        if (
            artifact.coordinate.group == _PROTOBUF_JAVA_RUNTIME_GROUP
            and artifact.coordinate.artifact == _PROTOBUF_JAVA_RUNTIME_ARTIFACT
        ):
            return ProtobufJavaRuntimeForResolve(tgt.address)

    raise MissingProtobufJavaRuntimeInResolveError(request.resolve_name)


@rule
async def inject_protobuf_java_runtime_dependency(
    request: InjectProtobufJavaRuntimeDependencyRequest,
    jvm: JvmSubsystem,
) -> InjectedDependencies:
    wrapped_target = await Get(WrappedTarget, Address, request.dependencies_field.address)
    target = wrapped_target.target

    if not target.has_field(JvmResolveField):
        return InjectedDependencies()
    resolve = target[JvmResolveField].normalized_value(jvm)

    protobuf_java_runtime_target_info = await Get(
        ProtobufJavaRuntimeForResolve, ProtobufJavaRuntimeForResolveRequest(resolve)
    )

    return InjectedDependencies((protobuf_java_runtime_target_info.address,))


class MissingProtobufJavaRuntimeInResolveError(ValueError):
    def __init__(self, resolve_name: str) -> None:
        super().__init__(
            f"The JVM resolve `{resolve_name}` does not contain a requirement for the protobuf-java "
            "runtime. Since at least one JVM target type in this repository consumes a "
            "`protobuf_sources` target in this resolve, the resolve must contain a `jvm_artifact` "
            "target for the protobuf-java` runtime.\n\n Please add the following `jvm_artifact` "
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
        UnionRule(InjectDependenciesRequest, InjectProtobufJavaRuntimeDependencyRequest),
    )
