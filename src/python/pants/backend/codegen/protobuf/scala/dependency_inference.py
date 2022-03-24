# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass

from pants.backend.codegen.protobuf.scala.subsystem import ScalaPBSubsystem
from pants.backend.codegen.protobuf.target_types import ProtobufDependenciesField
from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.build_graph.address import Address
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import InjectDependenciesRequest, InjectedDependencies, WrappedTarget
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference.artifact_mapper import AllJvmArtifactTargets
from pants.jvm.resolve.common import ArtifactRequirement, Coordinate
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.util.docutil import bin_name

_SCALAPB_RUNTIME_GROUP = "com.thesamet.scalapb"
_SCALAPB_RUNTIME_ARTIFACT = "scalapb-runtime"


class InjectScalaPBRuntimeDependencyRequest(InjectDependenciesRequest):
    inject_for = ProtobufDependenciesField


@dataclass(frozen=True)
class ScalaPBRuntimeForResolveRequest:
    resolve_name: str


@dataclass(frozen=True)
class ScalaPBRuntimeForResolve:
    address: Address


@rule
async def resolve_scalapb_runtime_for_resolve(
    request: ScalaPBRuntimeForResolveRequest,
    jvm_artifact_targets: AllJvmArtifactTargets,
    jvm: JvmSubsystem,
    scala_subsystem: ScalaSubsystem,
    scalapb: ScalaPBSubsystem,
) -> ScalaPBRuntimeForResolve:
    scala_version = scala_subsystem.version_for_resolve(request.resolve_name)
    # TODO: Does not handle Scala 3 suffix which is just `_3` nor X.Y.Z versions.
    scala_binary_version, _, _ = scala_version.rpartition(".")
    version = scalapb.version

    for tgt in jvm_artifact_targets:
        if tgt[JvmResolveField].normalized_value(jvm) != request.resolve_name:
            continue

        artifact = ArtifactRequirement.from_jvm_artifact_target(tgt)
        if (
            artifact.coordinate.group != _SCALAPB_RUNTIME_GROUP
            or artifact.coordinate.artifact != f"{_SCALAPB_RUNTIME_ARTIFACT}_{scala_binary_version}"
        ):
            continue

        if artifact.coordinate.version != version:
            raise ConflictingScalaPBRuntimeVersionInResolveError(
                request.resolve_name, version, artifact.coordinate
            )

        return ScalaPBRuntimeForResolve(tgt.address)

    raise MissingScalaPBRuntimeInResolveError(request.resolve_name, version, scala_binary_version)


@rule
async def inject_scalapb_runtime_dependency(
    request: InjectScalaPBRuntimeDependencyRequest,
    jvm: JvmSubsystem,
) -> InjectedDependencies:
    wrapped_target = await Get(WrappedTarget, Address, request.dependencies_field.address)
    target = wrapped_target.target

    if not target.has_field(JvmResolveField):
        return InjectedDependencies()
    resolve = target[JvmResolveField].normalized_value(jvm)

    scalapb_runtime_target_info = await Get(
        ScalaPBRuntimeForResolve, ScalaPBRuntimeForResolveRequest(resolve)
    )
    return InjectedDependencies((scalapb_runtime_target_info.address,))


class ConflictingScalaPBRuntimeVersionInResolveError(ValueError):
    """Exception for when there is a conflicting ScalaPB version in a resolve."""

    def __init__(
        self, resolve_name: str, required_version: str, conflicting_coordinate: Coordinate
    ) -> None:
        super().__init__(
            f"The JVM resolve `{resolve_name}` contains a `jvm_artifact` for version {conflicting_coordinate.version} "
            f"of the ScalaPB runtime. This conflicts with version {required_version} which is the configured version "
            "of ScalaPB for this resolve from the `[scalapb].version` option. "
            "Please remove the `jvm_artifact` target with JVM coordinate "
            f"{conflicting_coordinate.to_coord_str()}, then re-run "
            f"`{bin_name()} generate-lockfiles --resolve={resolve_name}`"
        )


class MissingScalaPBRuntimeInResolveError(ValueError):
    def __init__(self, resolve_name: str, version: str, scala_binary_version: str) -> None:
        super().__init__(
            f"The JVM resolve `{resolve_name}` does not contain a requirement for the ScalaPB runtime. "
            "Since at least one Scala target type in this repository consumes a `protobuf_sources` target "
            "in this resolve, the resolve must contain a `jvm_artifact` target for the ScalaPB runtime.\n\n"
            "Please add the following `jvm_artifact` target somewhere in the repository and re-run "
            f"`{bin_name()} generate-lockfiles --resolve={resolve_name}`:\n"
            "jvm_artifact(\n"
            f'  name="{_SCALAPB_RUNTIME_GROUP}_{_SCALAPB_RUNTIME_ARTIFACT}_{scala_binary_version}",\n'
            f'  group="{_SCALAPB_RUNTIME_GROUP}",\n',
            f'  artifact="{_SCALAPB_RUNTIME_ARTIFACT}_{scala_binary_version}",\n',
            f'  version="{version}",\n',
            f'  resolve="{resolve_name}",\n',
            ")",
        )


def rules():
    return (
        *collect_rules(),
        UnionRule(InjectDependenciesRequest, InjectScalaPBRuntimeDependencyRequest),
    )
