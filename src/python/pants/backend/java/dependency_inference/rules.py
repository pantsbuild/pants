# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging

from pants.backend.java.dependency_inference import import_parser, java_parser, symbol_mapper
from pants.backend.java.dependency_inference.types import JavaSourceDependencyAnalysis
from pants.backend.java.subsystems.java_infer import JavaInferSubsystem
from pants.backend.java.target_types import JavaSourceField
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.source_files import rules as source_files_rules
from pants.engine.addresses import Address
from pants.engine.rules import Get, MultiGet, collect_rules, rule
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
from pants.jvm.dependency_inference.artifact_mapper import (
    ThirdPartyPackageToArtifactMapping,
    find_artifact_mapping,
)
from pants.jvm.dependency_inference.symbol_mapper import FirstPartySymbolMapping
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet

logger = logging.getLogger(__name__)


class InferJavaSourceDependencies(InferDependenciesRequest):
    infer_from = JavaSourceField


@rule(desc="Inferring Java dependencies by analyzing imports")
async def infer_java_dependencies_via_imports(
    request: InferJavaSourceDependencies,
    java_infer_subsystem: JavaInferSubsystem,
    first_party_dep_map: FirstPartySymbolMapping,
    third_party_artifact_mapping: ThirdPartyPackageToArtifactMapping,
) -> InferredDependencies:
    if (
        not java_infer_subsystem.imports
        and not java_infer_subsystem.consumed_types
        and not java_infer_subsystem.third_party_imports
    ):
        return InferredDependencies([])

    address = request.sources_field.address
    wrapped_tgt = await Get(WrappedTarget, Address, address)
    explicitly_provided_deps, analysis = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(wrapped_tgt.target[Dependencies])),
        Get(JavaSourceDependencyAnalysis, SourceFilesRequest([request.sources_field])),
    )

    types: OrderedSet[str] = OrderedSet()
    if java_infer_subsystem.imports:
        types.update(dependency_name(imp.name, imp.is_static) for imp in analysis.imports)
    if java_infer_subsystem.consumed_types:
        package = analysis.declared_package

        # 13545: `analysis.consumed_types` may be unqualified (package-local or imported) or qualified
        # (prefixed by package name). Heuristic for now is that if there's a `.` in the type name, it's
        # probably fully qualified. This is probably fine for now.
        maybe_qualify_types = (
            f"{package}.{consumed_type}" if package and "." not in consumed_type else consumed_type
            for consumed_type in analysis.consumed_types
        )

        types.update(maybe_qualify_types)

    dep_map = first_party_dep_map.symbols

    dependencies: OrderedSet[Address] = OrderedSet()

    for typ in types:
        first_party_matches = dep_map.addresses_for_symbol(typ)
        third_party_matches: FrozenOrderedSet[Address] = FrozenOrderedSet()
        if java_infer_subsystem.third_party_imports:
            third_party_matches = find_artifact_mapping(typ, third_party_artifact_mapping)
        matches = first_party_matches.union(third_party_matches)
        if not matches:
            continue

        explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
            matches,
            address,
            import_reference="type",
            context=f"The target {address} imports `{typ}`",
        )
        maybe_disambiguated = explicitly_provided_deps.disambiguated(matches)
        if maybe_disambiguated:
            dependencies.add(maybe_disambiguated)

    return InferredDependencies(dependencies)


def dependency_name(name: str, static: bool):
    if not static:
        return name
    else:
        return name.rsplit(".", maxsplit=1)[0]


def rules():
    return [
        *collect_rules(),
        *artifact_mapper.rules(),
        *java_parser.rules(),
        *import_parser.rules(),
        *symbol_mapper.rules(),
        *source_files_rules(),
        UnionRule(InferDependenciesRequest, InferJavaSourceDependencies),
    ]
