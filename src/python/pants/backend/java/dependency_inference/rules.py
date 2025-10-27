# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

from pants.backend.java.dependency_inference import symbol_mapper
from pants.backend.java.dependency_inference.java_parser import (
    JavaSourceDependencyAnalysisRequest,
    resolve_fallible_result_to_analysis,
)
from pants.backend.java.dependency_inference.java_parser import rules as java_parser_rules
from pants.backend.java.dependency_inference.types import JavaImport
from pants.backend.java.subsystems.java_infer import JavaInferSubsystem
from pants.backend.java.target_types import JavaSourceField
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.core.util_rules.source_files import rules as source_files_rules
from pants.engine.addresses import Address
from pants.engine.internals.graph import determine_explicitly_provided_dependencies, resolve_target
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    FieldSet,
    InferDependenciesRequest,
    InferredDependencies,
    SourcesField,
    WrappedTargetRequest,
)
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference import artifact_mapper
from pants.jvm.dependency_inference.symbol_mapper import SymbolMapping
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet

logger = logging.getLogger(__name__)


# Java standard library package prefixes - types starting with these are always fully qualified
JAVA_STDLIB_PREFIXES = frozenset([
    "java.",
    "javax.",
    "jakarta.",
    "jdk.",
    "com.sun.",
    "sun.",  # Oracle internal
    "org.w3c.",
    "org.xml.",
    "org.ietf.",
    "org.omg.",  # Standards
])


def qualify_consumed_type(
    type_name: str,
    source_package: str | None,
    imports: tuple[JavaImport, ...],
) -> tuple[str, ...]:
    """
    Qualify a consumed type name, returning all possible qualified names to try.

    Returns a tuple of candidates in priority order. The symbol map should be checked
    for each candidate until a match is found.

    For inner classes, we return both the full inner class name and the outer class name,
    since the symbol mapper only indexes top-level types.

    Args:
        type_name: The type name as it appears in the source (may be qualified or unqualified)
        source_package: The package of the source file, or None if unnamed package
        imports: The imports declared in the source file

    Returns:
        Tuple of possible fully-qualified type names, in priority order
    """
    # Case 1: No dots - definitely unqualified, needs package prefix
    if "." not in type_name:
        if source_package:
            return (f"{source_package}.{type_name}",)
        else:
            return (type_name,)  # Unnamed package

    # Case 2: Known JDK/stdlib type - already fully qualified
    if any(type_name.startswith(prefix) for prefix in JAVA_STDLIB_PREFIXES):
        return (type_name,)

    # Case 3: Type appears in imports - already resolved
    # Check both regular imports and static imports
    import_names = {imp.name for imp in imports}
    if type_name in import_names:
        return (type_name,)

    # Also check if the first part of a dotted name is imported
    # E.g., "Outer.Inner" where "com.example.Outer" is imported
    first_part = type_name.split(".")[0]
    for imp in imports:
        if imp.name.endswith(f".{first_part}"):
            # The outer class is imported, so this is likely a reference to its inner class
            # Return the outer class name from the import for symbol lookup
            return (imp.name,)

    # Case 4: Ambiguous - has dots but not stdlib, not imported
    # Could be:
    #   a) Inner class from same package: "Outer.Inner" -> look up "com.example.Outer"
    #   b) Third-party FQTN: "org.apache.commons.Lang" -> "org.apache.commons.Lang"
    #   c) Inner class from imported outer: handled above

    # Strategy: For same-package inner classes, look up the outer class
    # The symbol mapper only indexes top-level types, so "com.example.Outer.Inner"
    # should be looked up as "com.example.Outer"
    if source_package:
        # Try as inner class first (look up outer class)
        outer_class = type_name.split(".")[0]
        qualified_outer = f"{source_package}.{outer_class}"
        # Also try as third-party FQTN
        return (qualified_outer, type_name)
    else:
        return (type_name,)


@dataclass(frozen=True)
class JavaSourceDependenciesInferenceFieldSet(FieldSet):
    required_fields = (JavaSourceField,)

    source: JavaSourceField


class InferJavaSourceDependencies(InferDependenciesRequest):
    infer_from = JavaSourceDependenciesInferenceFieldSet


@dataclass(frozen=True)
class JavaInferredDependencies:
    dependencies: FrozenOrderedSet[Address]
    exports: FrozenOrderedSet[Address]


@dataclass(frozen=True)
class JavaInferredDependenciesAndExportsRequest:
    source: SourcesField


@rule(desc="Inferring Java dependencies and exports by source analysis")
async def infer_java_dependencies_and_exports_via_source_analysis(
    request: JavaInferredDependenciesAndExportsRequest,
    java_infer_subsystem: JavaInferSubsystem,
    jvm: JvmSubsystem,
    symbol_mapping: SymbolMapping,
) -> JavaInferredDependencies:
    if not java_infer_subsystem.imports and not java_infer_subsystem.consumed_types:
        return JavaInferredDependencies(FrozenOrderedSet([]), FrozenOrderedSet([]))

    address = request.source.address

    wrapped_tgt = await resolve_target(
        WrappedTargetRequest(address, description_of_origin="<infallible>"), **implicitly()
    )
    tgt = wrapped_tgt.target
    source_files = await determine_source_files(SourceFilesRequest([tgt[JavaSourceField]]))

    explicitly_provided_deps, analysis = await concurrently(
        determine_explicitly_provided_dependencies(
            **implicitly(DependenciesRequest(tgt[Dependencies]))
        ),
        resolve_fallible_result_to_analysis(
            **implicitly(JavaSourceDependencyAnalysisRequest(source_files=source_files))
        ),
    )

    types: OrderedSet[str] = OrderedSet()
    if java_infer_subsystem.imports:
        types.update(dependency_name(imp) for imp in analysis.imports)
    if java_infer_subsystem.consumed_types:
        package = analysis.declared_package

        # Qualify each consumed type, potentially generating multiple candidates
        for consumed_type in analysis.consumed_types:
            candidates = qualify_consumed_type(consumed_type, package, analysis.imports)
            types.update(candidates)

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

    resolve = tgt[JvmResolveField].normalized_value(jvm)

    dependencies: OrderedSet[Address] = OrderedSet()
    exports: OrderedSet[Address] = OrderedSet()
    for typ in types:
        matches_by_ns = symbol_mapping.addresses_for_symbol(typ, resolve)
        if not matches_by_ns:
            logger.debug(
                f"No matches found for type '{typ}' in resolve '{resolve}' "
                f"(source file: {address})"
            )
            continue

        for matches in matches_by_ns.values():
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


@rule(desc="Inferring Java dependencies by source analysis")
async def infer_java_dependencies_via_source_analysis(
    request: InferJavaSourceDependencies,
) -> InferredDependencies:
    jids = await infer_java_dependencies_and_exports_via_source_analysis(
        JavaInferredDependenciesAndExportsRequest(request.field_set.source), **implicitly()
    )
    return InferredDependencies(jids.dependencies)


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
