# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.scala.compile import scalac_plugins
from pants.backend.scala.compile.scalac_plugins import (
    ScalaPluginsForTargetWithoutResolveRequest,
    ScalaPluginTargetsForTarget,
)
from pants.backend.scala.dependency_inference import scala_parser, symbol_mapper
from pants.backend.scala.dependency_inference.scala_parser import ScalaSourceDependencyAnalysis
from pants.backend.scala.resolve.lockfile import (
    SCALA_LIBRARY_ARTIFACT,
    SCALA_LIBRARY_GROUP,
    ConflictingScalaLibraryVersionInResolveError,
    MissingScalaLibraryInResolveError,
)
from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.backend.scala.subsystems.scala_infer import ScalaInferSubsystem
from pants.backend.scala.target_types import ScalaDependenciesField, ScalaSourceField
from pants.build_graph.address import Address
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    InferDependenciesRequest,
    InferredDependencies,
    InjectDependenciesRequest,
    InjectedDependencies,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference import artifact_mapper
from pants.jvm.dependency_inference.artifact_mapper import (
    AllJvmArtifactTargets,
    ThirdPartyPackageToArtifactMapping,
)
from pants.jvm.dependency_inference.symbol_mapper import FirstPartySymbolMapping
from pants.jvm.resolve.common import ArtifactRequirement
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.util.ordered_set import OrderedSet


class InferScalaSourceDependencies(InferDependenciesRequest):
    infer_from = ScalaSourceField


@rule(desc="Inferring Scala dependencies by analyzing sources")
async def infer_scala_dependencies_via_source_analysis(
    request: InferScalaSourceDependencies,
    scala_infer_subsystem: ScalaInferSubsystem,
    jvm: JvmSubsystem,
    first_party_symbol_map: FirstPartySymbolMapping,
    third_party_artifact_mapping: ThirdPartyPackageToArtifactMapping,
) -> InferredDependencies:
    if not scala_infer_subsystem.imports:
        return InferredDependencies([])

    address = request.sources_field.address
    wrapped_tgt = await Get(WrappedTarget, Address, address)
    tgt = wrapped_tgt.target
    explicitly_provided_deps, analysis = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(tgt[Dependencies])),
        Get(ScalaSourceDependencyAnalysis, SourceFilesRequest([request.sources_field])),
    )

    symbols: OrderedSet[str] = OrderedSet()
    if scala_infer_subsystem.imports:
        symbols.update(analysis.all_imports())
    if scala_infer_subsystem.consumed_types:
        symbols.update(analysis.fully_qualified_consumed_symbols())

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


class InjectScalaLibraryDependencyRequest(InjectDependenciesRequest):
    inject_for = ScalaDependenciesField


class InjectScalaPluginDependenciesRequest(InjectDependenciesRequest):
    inject_for = ScalaDependenciesField


@dataclass(frozen=True)
class ScalaRuntimeForResolveRequest:
    resolve_name: str


@dataclass(frozen=True)
class ScalaRuntimeForResolve:
    address: Address


@rule
async def resolve_scala_library_for_resolve(
    request: ScalaRuntimeForResolveRequest,
    jvm_artifact_targets: AllJvmArtifactTargets,
    jvm: JvmSubsystem,
    scala_subsystem: ScalaSubsystem,
) -> ScalaRuntimeForResolve:

    scala_version = scala_subsystem.version_for_resolve(request.resolve_name)

    for tgt in jvm_artifact_targets:
        if tgt[JvmResolveField].normalized_value(jvm) != request.resolve_name:
            continue

        artifact = ArtifactRequirement.from_jvm_artifact_target(tgt)
        if (
            artifact.coordinate.group != SCALA_LIBRARY_GROUP
            or artifact.coordinate.artifact != SCALA_LIBRARY_ARTIFACT
        ):
            continue

        if artifact.coordinate.version != scala_version:
            raise ConflictingScalaLibraryVersionInResolveError(
                request.resolve_name, scala_version, artifact.coordinate
            )

        return ScalaRuntimeForResolve(tgt.address)

    raise MissingScalaLibraryInResolveError(request.resolve_name, scala_version)


@rule(desc="Inject dependency on scala-library artifact for Scala target.")
async def inject_scala_library_dependency(
    request: InjectScalaLibraryDependencyRequest,
    jvm: JvmSubsystem,
) -> InjectedDependencies:
    wrapped_target = await Get(WrappedTarget, Address, request.dependencies_field.address)
    target = wrapped_target.target

    if not target.has_field(JvmResolveField):
        return InjectedDependencies()
    resolve = target[JvmResolveField].normalized_value(jvm)

    scala_library_target_info = await Get(
        ScalaRuntimeForResolve, ScalaRuntimeForResolveRequest(resolve)
    )
    return InjectedDependencies((scala_library_target_info.address,))


@rule(desc="Inject dependency on scala plugin artifacts for Scala target.")
async def inject_scala_plugin_dependencies(
    request: InjectScalaPluginDependenciesRequest,
) -> InjectedDependencies:
    """Adds dependencies on plugins for scala source files, so that they get included in the
    target's resolve."""

    wrapped_target = await Get(WrappedTarget, Address, request.dependencies_field.address)
    target = wrapped_target.target

    if not target.has_field(JvmResolveField):
        return InjectedDependencies()

    scala_plugins = await Get(
        ScalaPluginTargetsForTarget, ScalaPluginsForTargetWithoutResolveRequest(target)
    )

    plugin_addresses = [target.address for target in scala_plugins.artifacts]

    return InjectedDependencies(plugin_addresses)


def rules():
    return [
        *collect_rules(),
        *artifact_mapper.rules(),
        *scala_parser.rules(),
        *scalac_plugins.rules(),
        *symbol_mapper.rules(),
        UnionRule(InferDependenciesRequest, InferScalaSourceDependencies),
        UnionRule(InjectDependenciesRequest, InjectScalaLibraryDependencyRequest),
        UnionRule(InjectDependenciesRequest, InjectScalaPluginDependenciesRequest),
    ]
