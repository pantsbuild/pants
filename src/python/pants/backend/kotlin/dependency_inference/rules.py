# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.kotlin.dependency_inference import kotlin_parser, symbol_mapper
from pants.backend.kotlin.dependency_inference.kotlin_parser import (
    resolve_fallible_result_to_analysis,
)
from pants.backend.kotlin.subsystems.kotlin import KotlinSubsystem
from pants.backend.kotlin.subsystems.kotlin_infer import KotlinInferSubsystem
from pants.backend.kotlin.target_types import KotlinDependenciesField, KotlinSourceField
from pants.build_graph.address import Address
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.engine.internals.graph import determine_explicitly_provided_dependencies
from pants.engine.internals.selectors import concurrently
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import (
    DependenciesRequest,
    FieldSet,
    InferDependenciesRequest,
    InferredDependencies,
)
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference import artifact_mapper
from pants.jvm.dependency_inference import symbol_mapper as jvm_symbol_mapper
from pants.jvm.dependency_inference.artifact_mapper import (
    AllJvmArtifactTargets,
    find_jvm_artifacts_or_raise,
)
from pants.jvm.dependency_inference.symbol_mapper import SymbolMapping
from pants.jvm.resolve.coordinate import Coordinate
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.util.ordered_set import OrderedSet


@dataclass(frozen=True)
class KotlinSourceDependenciesInferenceFieldSet(FieldSet):
    required_fields = (KotlinSourceField, KotlinDependenciesField, JvmResolveField)

    source: KotlinSourceField
    dependencies: KotlinDependenciesField
    resolve: JvmResolveField


class InferKotlinSourceDependencies(InferDependenciesRequest):
    infer_from = KotlinSourceDependenciesInferenceFieldSet


@rule(desc="Inferring Kotlin dependencies by analyzing sources")
async def infer_kotlin_dependencies_via_source_analysis(
    request: InferKotlinSourceDependencies,
    kotlin_infer_subsystem: KotlinInferSubsystem,
    jvm: JvmSubsystem,
    symbol_mapping: SymbolMapping,
) -> InferredDependencies:
    if not kotlin_infer_subsystem.imports:
        return InferredDependencies([])

    address = request.field_set.address
    explicitly_provided_deps, analysis = await concurrently(
        determine_explicitly_provided_dependencies(
            **implicitly(DependenciesRequest(request.field_set.dependencies))
        ),
        resolve_fallible_result_to_analysis(
            **implicitly(SourceFilesRequest([request.field_set.source]))
        ),
    )

    symbols: OrderedSet[str] = OrderedSet()
    if kotlin_infer_subsystem.imports:
        symbols.update(imp.name for imp in analysis.imports)
    if kotlin_infer_subsystem.consumed_types:
        symbols.update(analysis.fully_qualified_consumed_symbols())

    resolve = request.field_set.resolve.normalized_value(jvm)

    dependencies: OrderedSet[Address] = OrderedSet()
    for symbol in symbols:
        for matches in symbol_mapping.addresses_for_symbol(symbol, resolve).values():
            explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
                matches,
                address,
                import_reference="type",
                context=f"The target {address} imports `{symbol}`",
            )

            maybe_disambiguated = explicitly_provided_deps.disambiguated(matches)
            if maybe_disambiguated:
                dependencies.add(maybe_disambiguated)

    return InferredDependencies(dependencies)


@dataclass(frozen=True)
class KotlinRuntimeDependencyInferenceFieldSet(FieldSet):
    required_fields = (KotlinDependenciesField, JvmResolveField)

    dependencies: KotlinDependenciesField
    resolve: JvmResolveField


class InferKotlinRuntimeDependencyRequest(InferDependenciesRequest):
    infer_from = KotlinRuntimeDependencyInferenceFieldSet


@dataclass(frozen=True)
class KotlinRuntimeForResolveRequest:
    resolve_name: str


@dataclass(frozen=True)
class KotlinRuntimeForResolve:
    addresses: frozenset[Address]


@rule
async def resolve_kotlin_runtime_for_resolve(
    request: KotlinRuntimeForResolveRequest,
    jvm_artifact_targets: AllJvmArtifactTargets,
    jvm: JvmSubsystem,
    kotlin_subsystem: KotlinSubsystem,
) -> KotlinRuntimeForResolve:
    kotlin_version = kotlin_subsystem.version_for_resolve(request.resolve_name)
    addresses = find_jvm_artifacts_or_raise(
        required_coordinates=[
            Coordinate(
                group="org.jetbrains.kotlin",
                artifact="kotlin-stdlib",
                version=kotlin_version,
            ),
            Coordinate(
                group="org.jetbrains.kotlin",
                artifact="kotlin-reflect",
                version=kotlin_version,
            ),
            Coordinate(
                group="org.jetbrains.kotlin",
                artifact="kotlin-script-runtime",
                version=kotlin_version,
            ),
        ],
        resolve=request.resolve_name,
        jvm_artifact_targets=jvm_artifact_targets,
        jvm=jvm,
        subsystem="the Kotlin runtime",
        target_type="kotlin_sources",
        requirement_source="the relevant entry for this resolve in the `[kotlin].version_for_resolve` option",
    )
    return KotlinRuntimeForResolve(addresses)


@rule(desc="Infer dependency on Kotlin runtime artifacts for Kotlin targets.")
async def infer_kotlin_stdlib_dependency(
    request: InferKotlinRuntimeDependencyRequest,
    jvm: JvmSubsystem,
) -> InferredDependencies:
    resolve = request.field_set.resolve.normalized_value(jvm)

    kotlin_runtime_target_info = await resolve_kotlin_runtime_for_resolve(
        KotlinRuntimeForResolveRequest(resolve), **implicitly()
    )
    return InferredDependencies(kotlin_runtime_target_info.addresses)


def rules():
    return (
        *collect_rules(),
        *kotlin_parser.rules(),
        *symbol_mapper.rules(),
        *jvm_symbol_mapper.rules(),
        *artifact_mapper.rules(),
        UnionRule(InferDependenciesRequest, InferKotlinSourceDependencies),
        UnionRule(InferDependenciesRequest, InferKotlinRuntimeDependencyRequest),
    )
