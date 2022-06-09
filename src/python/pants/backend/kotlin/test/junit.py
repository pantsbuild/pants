# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.kotlin.subsystems.kotlin import KotlinSubsystem
from pants.backend.kotlin.target_types import KotlinJunitTestDependenciesField
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
    find_jvm_artifacts_or_raise,
)
from pants.jvm.resolve.common import Coordinate
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField


class InjectKotlinJunitTestDependencyRequest(InjectDependenciesRequest):
    inject_for = KotlinJunitTestDependenciesField


@dataclass(frozen=True)
class KotlinJunitLibrariesForResolveRequest:
    resolve_name: str


@dataclass(frozen=True)
class KotlinJunitLibrariesForResolve:
    addresses: frozenset[Address]


@rule
async def resolve_kotlin_junit_libraries_for_resolve(
    request: KotlinJunitLibrariesForResolveRequest,
    jvm_artifact_targets: AllJvmArtifactTargets,
    jvm: JvmSubsystem,
    kotlin_subsystem: KotlinSubsystem,
) -> KotlinJunitLibrariesForResolve:
    kotlin_version = kotlin_subsystem.version_for_resolve(request.resolve_name)

    # TODO: Nicer exception messages if this fails due to the resolve missing a jar.
    addresses = find_jvm_artifacts_or_raise(
        required_coordinates=[
            Coordinate(
                group="org.jetbrains.kotlin",
                artifact="kotlin-test-junit",
                version=kotlin_version,
            ),
        ],
        resolve=request.resolve_name,
        jvm_artifact_targets=jvm_artifact_targets,
        jvm=jvm,
    )
    return KotlinJunitLibrariesForResolve(addresses)


@rule(desc="Inject dependency on Kotlin Junit support artifact.")
async def inject_kotlin_junit_dependency(
    request: InjectKotlinJunitTestDependencyRequest,
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

    kotlin_junit_libraries = await Get(
        KotlinJunitLibrariesForResolve, KotlinJunitLibrariesForResolveRequest(resolve)
    )
    return InjectedDependencies(kotlin_junit_libraries.addresses)


def rules():
    return (
        *collect_rules(),
        UnionRule(InjectDependenciesRequest, InjectKotlinJunitTestDependencyRequest),
    )
