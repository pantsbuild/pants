# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.kotlin.subsystems.kotlin import KotlinSubsystem
from pants.backend.kotlin.target_types import KotlinJunitTestDependenciesField
from pants.build_graph.address import Address
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, InferDependenciesRequest, InferredDependencies
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference.artifact_mapper import (
    AllJvmArtifactTargets,
    find_jvm_artifacts_or_raise,
)
from pants.jvm.resolve.coordinate import Coordinate
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField


@dataclass(frozen=True)
class KotlinJunitTestDependencyInferenceFieldSet(FieldSet):
    required_fields = (KotlinJunitTestDependenciesField, JvmResolveField)

    dependencies: KotlinJunitTestDependenciesField
    resolve: JvmResolveField


class InferKotlinJunitTestDependencyRequest(InferDependenciesRequest):
    infer_from = KotlinJunitTestDependencyInferenceFieldSet


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
        subsystem="the Kotlin test runtime for JUnit",
        target_type="kotlin_junit_tests",
        requirement_source="the relevant entry for this resolve in the `[kotlin].version_for_resolve` option",
    )
    return KotlinJunitLibrariesForResolve(addresses)


@rule(desc="Infer dependency on Kotlin Junit support artifact.")
async def infer_kotlin_junit_dependency(
    request: InferKotlinJunitTestDependencyRequest,
    jvm: JvmSubsystem,
) -> InferredDependencies:
    resolve = request.field_set.resolve.normalized_value(jvm)

    kotlin_junit_libraries = await Get(
        KotlinJunitLibrariesForResolve, KotlinJunitLibrariesForResolveRequest(resolve)
    )
    return InferredDependencies(kotlin_junit_libraries.addresses)


def rules():
    return (
        *collect_rules(),
        UnionRule(InferDependenciesRequest, InferKotlinJunitTestDependencyRequest),
    )
