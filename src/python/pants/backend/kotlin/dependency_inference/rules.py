# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.kotlin.dependency_inference import kotlin_parser, symbol_mapper
from pants.backend.kotlin.dependency_inference.kotlin_parser import KotlinSourceDependencyAnalysis
from pants.backend.kotlin.subsystems.kotlin_infer import KotlinInferSubsystem
from pants.backend.kotlin.target_types import KotlinSourceField
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
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference import artifact_mapper
from pants.jvm.dependency_inference import symbol_mapper as jvm_symbol_mapper
from pants.jvm.dependency_inference.artifact_mapper import ThirdPartyPackageToArtifactMapping
from pants.jvm.dependency_inference.symbol_mapper import FirstPartySymbolMapping
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
    first_party_symbol_map: FirstPartySymbolMapping,
    third_party_artifact_mapping: ThirdPartyPackageToArtifactMapping,
) -> InferredDependencies:
    if not kotlin_infer_subsystem.imports:
        return InferredDependencies([])

    address = request.sources_field.address
    wrapped_tgt = await Get(WrappedTarget, Address, address)
    tgt = wrapped_tgt.target
    explicitly_provided_deps, analysis = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(tgt[Dependencies])),
        Get(KotlinSourceDependencyAnalysis, SourceFilesRequest([request.sources_field])),
    )

    symbols: OrderedSet[str] = OrderedSet()
    if kotlin_infer_subsystem.imports:
        symbols.update(imp.name for imp in analysis.imports)

    resolve = tgt[JvmResolveField].normalized_value(jvm)

    dependencies: OrderedSet[Address] = OrderedSet()
    for symbol in symbols:
        first_party_matches = first_party_symbol_map.symbols.addresses_for_symbol(
            symbol, resolve=resolve
        )
        third_party_matches = third_party_artifact_mapping.addresses_for_symbol(symbol, resolve)
        matches = first_party_matches.union(third_party_matches)
        if not matches:
            continue

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


def rules():
    return (
        *collect_rules(),
        *kotlin_parser.rules(),
        *symbol_mapper.rules(),
        *jvm_symbol_mapper.rules(),
        *artifact_mapper.rules(),
        UnionRule(InferDependenciesRequest, InferKotlinSourceDependencies),
    )
