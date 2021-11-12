# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations
from dataclasses import dataclass

import logging
from itertools import groupby

from pants.backend.java.dependency_inference import (
    artifact_mapper,
    import_parser,
    package_mapper,
)
from pants.backend.java.dependency_inference.artifact_mapper import (
    AvailableThirdPartyArtifacts,
    ThirdPartyJavaPackageToArtifactMapping,
    find_artifact_mapping,
)
from pants.backend.java.dependency_inference.package_mapper import FirstPartyJavaPackageMapping
from pants.backend.java.dependency_inference.types import JavaSourceDependencyAnalysis
from pants.backend.java.subsystems.java_infer import JavaInferSubsystem
from pants.backend.java.target_types import JavaSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.source_files import rules as source_files_rules
from pants.engine.addresses import Address
from pants.engine.fs import Digest, PathGlobs, Snapshot
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
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.backend.java.dependency_inference.java_parser import rules as java_parser_rules, JavaSourceDependencyAnalysisRequest

logger = logging.getLogger(__name__)


class InferJavaSourceDependencies(InferDependenciesRequest):
    infer_from = JavaSourceField


@dataclass(frozen=True)
class JavaInferredDependencies:
    dependencies: FrozenOrderedSet[Address]
    exports: FrozenOrderedSet[Address]

@dataclass(frozen=True)
class JavaInferredDependenciesAndExportsRequest:
    address: Address

@rule(desc="Inferring Java dependencies by source analysis")
async def infer_java_dependencies_via_source_analysis(
    request: InferJavaSourceDependencies,
) -> InferredDependencies:

    jids = await Get(JavaInferredDependencies, JavaInferredDependenciesAndExportsRequest(request.sources_field.address))
    return InferredDependencies(dependencies=jids.dependencies)


@rule(desc="Inferring Java dependencies and exports by source analysis")
async def infer_java_dependencies_and_exports_via_source_analysis(
    request: JavaInferredDependenciesAndExportsRequest,
    java_infer_subsystem: JavaInferSubsystem,
    first_party_dep_map: FirstPartyJavaPackageMapping,
    third_party_artifact_mapping: ThirdPartyJavaPackageToArtifactMapping,
    available_artifacts: AvailableThirdPartyArtifacts,
) -> JavaInferredDependencies:
    if (
        not java_infer_subsystem.imports
        and not java_infer_subsystem.consumed_types
        and not java_infer_subsystem.third_party_imports
    ):
        return JavaInferredDependencies([], [])

    address = request.address
    if not address.is_file_target:
        raise Exception("Can only analyse file targets, Java ones at that")
    a = await Get(Digest, PathGlobs([address.filename]))
    s = await Get(Snapshot, Digest, a)

    wrapped_tgt = await Get(WrappedTarget, Address, address)
    explicitly_provided_deps, analysis = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(wrapped_tgt.target[Dependencies])),
        Get(JavaSourceDependencyAnalysis, JavaSourceDependencyAnalysisRequest(snapshot=s)),
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

    # Resolve the export types into (probable) types:
    consumed_type_mapping_ = sorted(((typ.rpartition(".")[2], typ) for typ in types))
    consumed_type_mapping__ = groupby(consumed_type_mapping_, lambda i: i[0])
    consumed_type_mapping = {i: {k[1] for k in j} for (i, j) in consumed_type_mapping__}
    export_types = {i for typ in analysis.export_types for i in consumed_type_mapping.get(typ, [])}
    export_types.update(typ for typ in analysis.export_types if "." in typ)

    dep_map = first_party_dep_map.package_rooted_dependency_map

    dependencies: OrderedSet[Address] = OrderedSet()
    exports: OrderedSet[Address] = OrderedSet()

    for typ in types:
        first_party_matches = dep_map.addresses_for_type(typ)
        third_party_matches: FrozenOrderedSet[Address] = FrozenOrderedSet()
        if java_infer_subsystem.third_party_imports:
            third_party_matches = find_artifact_mapping(
                typ, third_party_artifact_mapping, available_artifacts
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

    #logger.warning("%s", exports)

    # Files do not export themselves. Don't be silly.
    if address in exports:
        exports.remove(address)

    return JavaInferredDependencies(dependencies, exports)


def dependency_name(name: str, static: bool):
    if not static:
        return name
    else:
        return name.rsplit(".", maxsplit=1)[0]


def rules():
    return [
        *collect_rules(),
        *artifact_mapper.rules(),
        *java_parser_rules(),
        *import_parser.rules(),
        *package_mapper.rules(),
        *source_files_rules(),
        UnionRule(InferDependenciesRequest, InferJavaSourceDependencies),
    ]
