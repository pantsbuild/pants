# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

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

# Java standard library package prefixes - types starting with these are always fully qualified
JAVA_STDLIB_PREFIXES = frozenset([
    "java.", "javax.", "jakarta.", "jdk.",
    "com.sun.", "sun.",  # Oracle internal
    "org.w3c.", "org.xml.", "org.ietf.", "org.omg.",  # Standards
])


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
        type_candidates: OrderedSet[str] = OrderedSet()
        for consumed_type in analysis.consumed_types:
            candidates = qualify_consumed_type(consumed_type, package, analysis.imports)
            type_candidates.update(candidates)

        types.update(type_candidates)

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
        for matches in lookup_type_with_fallback(typ, symbol_mapping, resolve).values():
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

    # For each direct dependency, resolve its exported types as transitive dependencies
    # This handles the case where A imports B, and B has a field of type C
    # Even though A never imports C, the Java compiler needs C's class file
    direct_dependencies = list(dependencies)
    transitive_from_exports: OrderedSet[Address] = OrderedSet()

    for dep_address in direct_dependencies:
        # Only process first-party Java sources (not third-party artifacts)
        dep_wrapped = await resolve_target(
            WrappedTargetRequest(dep_address, description_of_origin="<infallible>"), **implicitly()
        )
        dep_tgt = dep_wrapped.target

        # Skip if not a Java source file
        if not dep_tgt.has_field(JavaSourceField):
            continue

        # Get the dependency's source analysis
        dep_source_files = await determine_source_files(SourceFilesRequest([dep_tgt[JavaSourceField]]))
        dep_analysis = await resolve_fallible_result_to_analysis(
            **implicitly(JavaSourceDependencyAnalysisRequest(source_files=dep_source_files))
        )

        # Get the dependency's package for qualifying its export types
        dep_package = dep_analysis.declared_package

        # Qualify each export type from the dependency
        for export_type in dep_analysis.export_types:
            # The export types from the dependency's analysis are from that file's perspective
            # We need to qualify them based on the dependency's package and imports
            export_candidates = qualify_consumed_type(export_type, dep_package, dep_analysis.imports)

            for qualified_export in export_candidates:
                # Look up the export type in the symbol map
                for matches in lookup_type_with_fallback(qualified_export, symbol_mapping, resolve).values():
                    maybe_disambiguated = explicitly_provided_deps.disambiguated(matches)
                    if maybe_disambiguated and maybe_disambiguated != dep_address:
                        transitive_from_exports.add(maybe_disambiguated)

    # Add transitive dependencies from exports
    dependencies.update(transitive_from_exports)

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


def qualify_consumed_type(
    type_name: str,
    source_package: str | None,
    imports: tuple[JavaImport, ...],
) -> tuple[str, ...]:
    """
    Qualify a consumed type name, returning possible qualified names to try.

    Returns a tuple of candidates in priority order. The symbol map should be checked
    for each candidate until a match is found.

    Args:
        type_name: The type name as it appears in the source (may be qualified or unqualified)
        source_package: The package of the source file, or None if unnamed package
        imports: The imports declared in the source file

    Returns:
        Tuple of possible fully-qualified type names, in priority order
    """
    # Case 1: No dots → definitely unqualified, needs package prefix
    if "." not in type_name:
        if source_package:
            return (f"{source_package}.{type_name}",)
        else:
            return (type_name,)  # Unnamed package

    # Case 2: Known JDK/stdlib type → already fully qualified
    if any(type_name.startswith(prefix) for prefix in JAVA_STDLIB_PREFIXES):
        return (type_name,)

    # Case 3: Type fully qualified name appears in imports → already resolved
    import_names = {imp.name for imp in imports}
    if type_name in import_names:
        return (type_name,)

    # Case 4: Outer class is imported → resolve inner class through import
    # E.g., "B.InnerB" where "com.other.B" is imported → "com.other.B.InnerB"
    first_part = type_name.split(".")[0]
    for imp in imports:
        if imp.name.endswith(f".{first_part}"):
            # Found import for outer class, construct fully qualified inner class name
            qualified = imp.name + type_name[len(first_part):]
            return (qualified,)

    # Case 5: Ambiguous - has dots but not stdlib, not imported
    # Most likely: same-package inner class like "B.InnerB" → "com.example.B.InnerB"
    # Less likely: third-party FQTN without import
    if source_package:
        # Try same-package first (most common), then as-is (fallback for third-party)
        return (f"{source_package}.{type_name}", type_name)
    else:
        return (type_name,)


def lookup_type_with_fallback(
    typ: str,
    symbol_mapping: SymbolMapping,
    resolve: str
) -> dict[str, FrozenOrderedSet[Address]]:
    """
    Look up a type in the symbol map, with fallback to parent types for inner classes.

    Args:
        typ: Fully qualified type name (e.g., "com.example.B.InnerB")
        symbol_mapping: The symbol map to search
        resolve: The JVM resolve to search within

    Returns:
        Dict mapping namespaces to addresses, empty if no match found
    """
    # Try exact match first
    matches = symbol_mapping.addresses_for_symbol(typ, resolve)
    if matches:
        return matches

    # If not found and typ looks like it might be an inner class (has dots after package)
    # Try stripping inner class parts one by one
    # E.g., "com.example.B.InnerB" → try "com.example.B"
    #       "com.example.Outer.Middle.Inner" → try "com.example.Outer.Middle", then "com.example.Outer"
    parts = typ.split(".")
    if len(parts) > 2:  # At least package + outer + inner
        for i in range(len(parts) - 1, 1, -1):  # Don't try single-part names
            parent_type = ".".join(parts[:i])
            matches = symbol_mapping.addresses_for_symbol(parent_type, resolve)
            if matches:
                return matches

    return {}


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
