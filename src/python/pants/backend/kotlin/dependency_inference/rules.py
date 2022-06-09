# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.kotlin.dependency_inference import kotlin_parser, symbol_mapper
from pants.backend.kotlin.dependency_inference.kotlin_parser import KotlinSourceDependencyAnalysis
from pants.backend.kotlin.subsystems.kotlin import KotlinSubsystem
from pants.backend.kotlin.subsystems.kotlin_infer import KotlinInferSubsystem
from pants.backend.kotlin.target_types import KotlinDependenciesField, KotlinSourceField
from pants.build_graph.address import Address
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    InferDependenciesRequest,
    InferredDependencies,
    InjectDependenciesRequest,
    InjectedDependencies,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference import artifact_mapper
from pants.jvm.dependency_inference import symbol_mapper as jvm_symbol_mapper
from pants.jvm.dependency_inference.artifact_mapper import (
    AllJvmArtifactTargets,
    find_jvm_artifacts_or_raise,
)
from pants.jvm.dependency_inference.symbol_mapper import SymbolMapping
from pants.jvm.resolve.common import Coordinate
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.util.ordered_set import OrderedSet


class InferKotlinSourceDependencies(InferDependenciesRequest):
    infer_from = KotlinSourceField


@rule(desc="Inferring Kotlin dependencies by analyzing sources")
async def infer_kotlin_dependencies_via_source_analysis(
    request: InferKotlinSourceDependencies,
    kotlin_infer_subsystem: KotlinInferSubsystem,
    jvm: JvmSubsystem,
    symbol_mapping: SymbolMapping,
) -> InferredDependencies:
    if not kotlin_infer_subsystem.imports:
        return InferredDependencies([])

    address = request.sources_field.address
    wrapped_tgt = await Get(
        WrappedTarget, WrappedTargetRequest(address, description_of_origin="<infallible>")
    )
    tgt = wrapped_tgt.target
    explicitly_provided_deps, analysis = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(tgt[Dependencies])),
        Get(KotlinSourceDependencyAnalysis, SourceFilesRequest([request.sources_field])),
    )

    symbols: OrderedSet[str] = OrderedSet()
    if kotlin_infer_subsystem.imports:
        symbols.update(imp.name for imp in analysis.imports)
    if kotlin_infer_subsystem.consumed_types:
        symbols.update(analysis.fully_qualified_consumed_symbols())

    resolve = tgt[JvmResolveField].normalized_value(jvm)

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


class InjectKotlinRuntimeDependencyRequest(InjectDependenciesRequest):
    inject_for = KotlinDependenciesField


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

    # TODO: Nicer exception messages if this fails due to the resolve missing a jar.
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
    )
    return KotlinRuntimeForResolve(addresses)


@rule(desc="Inject dependency on Kotlin runtime artifacts for Kotlin targets.")
async def inject_kotlin_stdlib_dependency(
    request: InjectKotlinRuntimeDependencyRequest,
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

    kotlin_runtime_target_info = await Get(
        KotlinRuntimeForResolve, KotlinRuntimeForResolveRequest(resolve)
    )
    return InjectedDependencies(kotlin_runtime_target_info.addresses)


def rules():
    return (
        *collect_rules(),
        *kotlin_parser.rules(),
        *symbol_mapper.rules(),
        *jvm_symbol_mapper.rules(),
        *artifact_mapper.rules(),
        UnionRule(InferDependenciesRequest, InferKotlinSourceDependencies),
        UnionRule(InjectDependenciesRequest, InjectKotlinRuntimeDependencyRequest),
    )
