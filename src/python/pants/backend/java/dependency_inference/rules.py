# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from pants.backend.java.dependency_inference import symbol_mapper
from pants.backend.java.dependency_inference.java_parser import JavaSourceDependencyAnalysisRequest
from pants.backend.java.dependency_inference.java_parser import rules as java_parser_rules
from pants.backend.java.dependency_inference.types import JavaImport, JavaSourceDependencyAnalysis
from pants.backend.java.subsystems.java_infer import JavaInferSubsystem
from pants.backend.java.target_types import JavaSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.source_files import rules as source_files_rules
from pants.engine.addresses import Address
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    InferDependenciesRequest,
    InferredDependencies,
    SourcesField,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference import artifact_mapper
from pants.jvm.dependency_inference.artifact_mapper import ThirdPartyPackageToArtifactMapping
from pants.jvm.dependency_inference.symbol_mapper import FirstPartySymbolMapping
from pants.jvm.subsystems import JvmSubsystem
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet


class InferJavaSourceDependencies(InferDependenciesRequest):
    infer_from = JavaSourceField


@dataclass(frozen=True)
class JavaInferredDependencies:
    dependencies: FrozenOrderedSet[Address]
    exports: FrozenOrderedSet[Address]


@dataclass(frozen=True)
class JavaInferredDependenciesAndExportsRequest:
    source: SourcesField


@rule(desc="Inferring Java dependencies by source analysis")
async def infer_java_dependencies_via_source_analysis(
    request: InferJavaSourceDependencies,
) -> InferredDependencies:

    jids = await Get(
        JavaInferredDependencies,
        JavaInferredDependenciesAndExportsRequest(request.sources_field),
    )
    return InferredDependencies(dependencies=jids.dependencies)


@rule(desc="Inferring Java dependencies and exports by source analysis")
async def infer_java_dependencies_and_exports_via_source_analysis(
    request: JavaInferredDependenciesAndExportsRequest,
    java_infer_subsystem: JavaInferSubsystem,
    jvm: JvmSubsystem,
    first_party_dep_map: FirstPartySymbolMapping,
    third_party_artifact_mapping: ThirdPartyPackageToArtifactMapping,
) -> JavaInferredDependencies:
    if (
        not java_infer_subsystem.imports
        and not java_infer_subsystem.consumed_types
        and not java_infer_subsystem.third_party_imports
    ):
        return JavaInferredDependencies(FrozenOrderedSet([]), FrozenOrderedSet([]))

    address = request.source.address

    wrapped_tgt = await Get(WrappedTarget, Address, address)
    tgt = wrapped_tgt.target
    source_files = await Get(SourceFiles, SourceFilesRequest([tgt[JavaSourceField]]))

    explicitly_provided_deps, analysis = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(tgt[Dependencies])),
        Get(
            JavaSourceDependencyAnalysis,
            JavaSourceDependencyAnalysisRequest(source_files=source_files),
        ),
    )

    types: OrderedSet[str] = OrderedSet()
    if java_infer_subsystem.imports:
        types.update(dependency_name(imp) for imp in analysis.imports)
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

    # Resolve the export types into (probable) types:
    # First produce a map of known consumed unqualified types to possible qualified names
    consumed_type_mapping: dict[str, set[str]] = defaultdict(set)
    for typ in types:
        unqualified = typ.rpartition(".")[2]  # `"org.foo.Java"` -> `("org.foo", ".", "Java")`
        consumed_type_mapping[unqualified].add(typ)

    # Now take the list of unqualified export types and convert them to possible
    # qualified names based on the guesses we made for consumed types
    export_types = {
        i for typ in analysis.export_types for i in consumed_type_mapping.get(typ, set())
    }
    # Finally, if there's a `.` in the name, it's probably fully qualified,
    # so just add it unaltered
    export_types.update(typ for typ in analysis.export_types if "." in typ)

    dep_map = first_party_dep_map.symbols
    resolves = jvm.resolves_for_target(tgt)

    dependencies: OrderedSet[Address] = OrderedSet()
    exports: OrderedSet[Address] = OrderedSet()

    for typ in types:
        first_party_matches = dep_map.addresses_for_symbol(typ)
        third_party_matches = (
            third_party_artifact_mapping.addresses_for_symbol(typ, resolves)
            if java_infer_subsystem.third_party_imports
            else FrozenOrderedSet()
        )
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
            if typ in export_types:
                exports.add(maybe_disambiguated)
        else:
            # Exports from explicitly provided dependencies:
            explicitly_provided_exports = set(matches) & set(explicitly_provided_deps.includes)
            exports.update(explicitly_provided_exports)

    # Files do not export themselves. Don't be silly.
    if address in exports:
        exports.remove(address)

    return JavaInferredDependencies(FrozenOrderedSet(dependencies), FrozenOrderedSet(exports))


def dependency_name(imp: JavaImport):
    if imp.is_static and not imp.is_asterisk:
        return imp.name.rsplit(".", maxsplit=1)[0]
    else:
        return imp.name


def rules():
    return [
        *collect_rules(),
        *artifact_mapper.rules(),
        *java_parser_rules(),
        *symbol_mapper.rules(),
        *source_files_rules(),
        UnionRule(InferDependenciesRequest, InferJavaSourceDependencies),
    ]
