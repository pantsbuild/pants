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

# Java standard library prefixes that are always fully qualified
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
    consumed_type: str, package: str | None, imports: frozenset[JavaImport]
) -> tuple[str, ...]:
    """
    Qualify a consumed type name, potentially returning multiple candidates.

    Handles multiple cases:
    - Case 1: Unqualified names (no dots) → add package prefix
    - Case 2: JDK/stdlib types → already fully qualified
    - Case 3: Type appears in imports → already resolved
    - Case 4: Outer class is imported → resolve inner class (e.g., B.InnerB when com.pkg.B imported)
    - Case 5: Ambiguous with dots → try same-package first, then as-is

    Returns tuple of candidate FQTNs in priority order.
    """
    # Case 1: Unqualified name (no dots) - add package prefix if available
    if "." not in consumed_type:
        if package:
            return (f"{package}.{consumed_type}",)
        else:
            return (consumed_type,)

    # Case 2: JDK/stdlib types - already fully qualified
    for prefix in JAVA_STDLIB_PREFIXES:
        if consumed_type.startswith(prefix):
            return (consumed_type,)

    # Build a map of imported type names (both simple and full)
    import_map: dict[str, str] = {}
    for imp in imports:
        full_name = dependency_name(imp)
        simple_name = full_name.rsplit(".", maxsplit=1)[-1]
        import_map[simple_name] = full_name
        import_map[full_name] = full_name

    # Case 3: Type appears in imports → already resolved
    if consumed_type in import_map:
        return (import_map[consumed_type],)

    # Case 4: Outer class is imported → resolve inner class
    # E.g., consumed_type is "B.InnerB" and "com.pkg.B" is imported
    first_part = consumed_type.split(".", maxsplit=1)[0]
    if first_part in import_map:
        outer_class_fqn = import_map[first_part]
        # Replace the simple name with the fully qualified name
        # "B.InnerB" with B→"com.pkg.B" becomes "com.pkg.B.InnerB"
        inner_part = consumed_type.split(".", maxsplit=1)[1]
        return (f"{outer_class_fqn}.{inner_part}",)

    # Case 5: Ambiguous with dots - try same-package first, then as-is
    # The type might be a same-package reference like "OtherClass.InnerClass"
    # or it might already be fully qualified
    candidates = []
    if package:
        candidates.append(f"{package}.{consumed_type}")
    candidates.append(consumed_type)
    return tuple(candidates)


def lookup_type_with_fallback(
    typ: str, symbol_mapping: SymbolMapping, resolve: str | None
) -> dict[str, tuple[Address, ...]]:
    """
    Search symbol map with inner class fallback.

    - Try exact match first
    - If not found and type has multiple dots, strip inner class parts iteratively
    - Example: com.example.B.InnerB → try com.example.B → find match

    Returns the same structure as symbol_mapping.addresses_for_symbol().
    """
    # Try exact match first
    result = symbol_mapping.addresses_for_symbol(typ, resolve)
    if result:
        return result

    # If not found and type has multiple dots, try stripping inner class parts
    if typ.count(".") >= 2:
        # Iteratively strip the last part until we find a match
        parts = typ.split(".")
        for i in range(len(parts) - 1, 1, -1):  # Stop at 2 parts (package.Class)
            candidate = ".".join(parts[:i])
            result = symbol_mapping.addresses_for_symbol(candidate, resolve)
            if result:
                return result

    # Return empty dict if no match found
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
