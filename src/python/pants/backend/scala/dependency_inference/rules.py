# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.scala.compile import scalac_plugins
from pants.backend.scala.dependency_inference import scala_parser, symbol_mapper
from pants.backend.scala.dependency_inference.scala_parser import (
    resolve_fallible_result_to_analysis,
)
from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.backend.scala.subsystems.scala_infer import ScalaInferSubsystem
from pants.backend.scala.target_types import ScalaDependenciesField, ScalaSourceField
from pants.backend.scala.util_rules import versions
from pants.backend.scala.util_rules.versions import (
    ScalaArtifactsForVersionRequest,
    resolve_scala_artifacts_for_version,
)
from pants.build_graph.address import Address
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.engine.internals.graph import determine_explicitly_provided_dependencies
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import (
    DependenciesRequest,
    FieldSet,
    InferDependenciesRequest,
    InferredDependencies,
)
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference import artifact_mapper
from pants.jvm.dependency_inference.artifact_mapper import (
    AllJvmArtifactTargets,
    find_jvm_artifacts_or_raise,
)
from pants.jvm.dependency_inference.symbol_mapper import SymbolMapping
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.util.ordered_set import OrderedSet


@dataclass(frozen=True)
class ScalaSourceDependenciesInferenceFieldSet(FieldSet):
    required_fields = (ScalaSourceField, ScalaDependenciesField, JvmResolveField)

    source: ScalaSourceField
    dependencies: ScalaDependenciesField
    resolve: JvmResolveField


class InferScalaSourceDependencies(InferDependenciesRequest):
    infer_from = ScalaSourceDependenciesInferenceFieldSet


@rule(desc="Inferring Scala dependencies by analyzing sources")
async def infer_scala_dependencies_via_source_analysis(
    request: InferScalaSourceDependencies,
    scala_infer_subsystem: ScalaInferSubsystem,
    jvm: JvmSubsystem,
    symbol_mapping: SymbolMapping,
) -> InferredDependencies:
    if not scala_infer_subsystem.imports:
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
    if scala_infer_subsystem.imports:
        symbols.update(analysis.all_imports())
    if scala_infer_subsystem.consumed_types:
        symbols.update(analysis.fully_qualified_consumed_symbols())
    if scala_infer_subsystem.package_objects:
        symbols.update(analysis.scopes)

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
class ScalaLibraryDependencyInferenceFieldSet(FieldSet):
    required_fields = (ScalaDependenciesField, JvmResolveField)

    dependencies: ScalaDependenciesField
    resolve: JvmResolveField


class InferScalaLibraryDependencyRequest(InferDependenciesRequest):
    infer_from = ScalaLibraryDependencyInferenceFieldSet


@dataclass(frozen=True)
class ScalaPluginDependencyInferenceFieldSet(FieldSet):
    required_fields = (ScalaDependenciesField, JvmResolveField)

    dependencies: ScalaDependenciesField
    resolve: JvmResolveField


@dataclass(frozen=True)
class ScalaRuntimeForResolveRequest:
    resolve_name: str


@dataclass(frozen=True)
class ScalaRuntimeForResolve:
    addresses: frozenset[Address]


@rule
async def resolve_scala_library_for_resolve(
    request: ScalaRuntimeForResolveRequest,
    jvm_artifact_targets: AllJvmArtifactTargets,
    jvm: JvmSubsystem,
    scala_subsystem: ScalaSubsystem,
) -> ScalaRuntimeForResolve:
    scala_version = scala_subsystem.version_for_resolve(request.resolve_name)
    scala_artifacts = await resolve_scala_artifacts_for_version(
        ScalaArtifactsForVersionRequest(scala_version)
    )

    addresses = find_jvm_artifacts_or_raise(
        required_coordinates=[
            scala_artifacts.library_coordinate,
        ],
        resolve=request.resolve_name,
        jvm_artifact_targets=jvm_artifact_targets,
        jvm=jvm,
        subsystem="the Scala runtime library",
        target_type="scala_sources",
        requirement_source="the relevant entry for this resolve in the `[scala].version_for_resolve` option",
    )
    return ScalaRuntimeForResolve(addresses)


@rule(desc="Infer dependency on scala-library artifact for Scala target.")
async def infer_scala_library_dependency(
    request: InferScalaLibraryDependencyRequest,
    jvm: JvmSubsystem,
) -> InferredDependencies:
    resolve = request.field_set.resolve.normalized_value(jvm)
    scala_library_target_info = await resolve_scala_library_for_resolve(
        ScalaRuntimeForResolveRequest(resolve), **implicitly()
    )
    return InferredDependencies(scala_library_target_info.addresses)


def rules():
    return [
        *collect_rules(),
        *artifact_mapper.rules(),
        *scala_parser.rules(),
        *scalac_plugins.rules(),
        *symbol_mapper.rules(),
        *versions.rules(),
        UnionRule(InferDependenciesRequest, InferScalaSourceDependencies),
        UnionRule(InferDependenciesRequest, InferScalaLibraryDependencyRequest),
    ]
