# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging

from pants.backend.scala.dependency_inference import scala_parser, symbol_mapper
from pants.backend.scala.dependency_inference.scala_parser import ScalaSourceDependencyAnalysis
from pants.backend.scala.dependency_inference.symbol_mapper import FirstPartyScalaSymbolMapping
from pants.backend.scala.subsystems.scala_infer import ScalaInferSubsystem
from pants.backend.scala.target_types import ScalaSourceField
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
from pants.util.ordered_set import OrderedSet

logger = logging.getLogger(__name__)


class InferScalaSourceDependencies(InferDependenciesRequest):
    infer_from = ScalaSourceField


@rule(desc="Inferring Scala dependencies by analyzing sources")
async def infer_scala_dependencies_via_source_analysis(
    request: InferScalaSourceDependencies,
    scala_infer_subsystem: ScalaInferSubsystem,
    first_party_symbol_map: FirstPartyScalaSymbolMapping,
) -> InferredDependencies:
    if not scala_infer_subsystem.imports:
        return InferredDependencies([])

    address = request.sources_field.address
    wrapped_tgt = await Get(WrappedTarget, Address, address)
    explicitly_provided_deps, analysis = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(wrapped_tgt.target[Dependencies])),
        Get(ScalaSourceDependencyAnalysis, SourceFilesRequest([request.sources_field])),
    )

    symbols: OrderedSet[str] = OrderedSet()
    if scala_infer_subsystem.imports:
        symbols.update(analysis.all_imports())

    dependencies: OrderedSet[Address] = OrderedSet()
    for symbol in symbols:
        matches = first_party_symbol_map.symbols.addresses_for_symbol(symbol)
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
    return [
        *collect_rules(),
        *scala_parser.rules(),
        *symbol_mapper.rules(),
    ]
