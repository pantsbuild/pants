# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, cast

from pants.backend.java.dependency_inference import (
    import_parser,
    java_parser,
    jvm_artifact_mappings,
    package_mapper,
)
from pants.backend.java.dependency_inference.jvm_artifact_mappings import JVM_ARTIFACT_MAPPINGS
from pants.backend.java.dependency_inference.package_mapper import FirstPartyJavaPackageMapping
from pants.backend.java.dependency_inference.types import JavaSourceDependencyAnalysis
from pants.backend.java.target_types import JavaSourceField
from pants.base.specs import AddressSpecs, MaybeEmptyDescendantAddresses
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
    UnexpandedTargets,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.jvm.target_types import JvmArtifactArtifactField, JvmArtifactGroupField
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet

logger = logging.getLogger(__name__)


class JavaInferSubsystem(Subsystem):
    options_scope = "java-infer"
    help = "Options controlling which dependencies will be inferred for Java targets."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--imports",
            default=True,
            type=bool,
            help=("Infer a target's dependencies by parsing import statements from sources."),
        )
        register(
            "--consumed-types",
            default=True,
            type=bool,
            help=("Infer a target's dependencies by parsing consumed types from sources."),
        )
        register(
            "--third-party-imports",
            default=True,
            type=bool,
            help="Infer a target's third-party dependencies using Java import statements.",
        )
        register(
            "--third-party-import-mapping",
            type=dict,
            default=JVM_ARTIFACT_MAPPINGS,
            help=(
                "Dictionary mapping a Java package prefix to either (1) a JVM artifact coordinate (GROUP:ARTIFACT) "
                "without the version; or (2) the value `SKIP` which causes that prefix to not be used for "
                "inference. (This dictionary is a flattened trie. Internally, Pants will convert the dictionary "
                "into the trie data structure actually used for dependency inference.)"
            ),
        )

    @property
    def imports(self) -> bool:
        return cast(bool, self.options.imports)

    @property
    def consumed_types(self) -> bool:
        return cast(bool, self.options.consumed_types)

    @property
    def third_party_imports(self) -> bool:
        return cast(bool, self.options.third_party_imports)

    @property
    def third_party_import_mapping(self) -> dict:
        return cast(dict, self.options.third_party_import_mapping)


class InferJavaSourceDependencies(InferDependenciesRequest):
    infer_from = JavaSourceField


@rule(desc="Inferring Java dependencies by analyzing imports")
async def infer_java_dependencies_via_imports(
    request: InferJavaSourceDependencies,
    java_infer_subsystem: JavaInferSubsystem,
    first_party_dep_map: FirstPartyJavaPackageMapping,
) -> InferredDependencies:
    if not java_infer_subsystem.imports and not java_infer_subsystem.consumed_types:
        return InferredDependencies([])

    address = request.sources_field.address
    wrapped_tgt = await Get(WrappedTarget, Address, address)
    explicitly_provided_deps, analysis = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(wrapped_tgt.target[Dependencies])),
        Get(JavaSourceDependencyAnalysis, SourceFilesRequest([request.sources_field])),
    )

    types: OrderedSet[str] = OrderedSet()
    if java_infer_subsystem.imports:
        types.update(imp.name for imp in analysis.imports)
    if java_infer_subsystem.consumed_types:
        package = analysis.declared_package
        types.update(
            f"{package}.{consumed_type}" for consumed_type in analysis.consumed_unqualified_types
        )

    dep_map = first_party_dep_map.package_rooted_dependency_map

    dependencies: OrderedSet[Address] = OrderedSet()
    for typ in types:
        matches = dep_map.addresses_for_type(typ)
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


# -----------------------------------------------------------------------------------------------
# Third-party package dependency inference
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class UnversionedCoordinate:
    group: str
    artifact: str

    @classmethod
    def from_coord_str(cls, coord: str) -> UnversionedCoordinate:
        coordinate_parts = coord.split(":")
        if len(coordinate_parts) != 2:
            raise ValueError(f"Invalid coordinate specifier: {coord}")
        return UnversionedCoordinate(group=coordinate_parts[0], artifact=coordinate_parts[1])


@dataclass(frozen=True)
class AvailableThirdPartyArtifacts:
    """Maps JVM artifact coordinates (with only group and artifact set) to the `Address` of each
    target specifying that coordinate."""

    artifacts: FrozenDict[UnversionedCoordinate, FrozenOrderedSet[Address]]


@dataclass(frozen=True)
class ThirdPartyJavaPackageToArtifactMapping:
    # TODO: Find a way to specify the nested trie dictionary structure in mypy.
    mapping: FrozenDict[Any, Any]


class InferJavaThirdPartyImportDependencies(InferDependenciesRequest):
    infer_from = JavaSourceField


@rule
async def find_available_third_party_artifacts() -> AvailableThirdPartyArtifacts:
    all_targets = await Get(UnexpandedTargets, AddressSpecs([MaybeEmptyDescendantAddresses("")]))
    jvm_artifact_targets = [
        tgt
        for tgt in all_targets
        if tgt.has_fields((JvmArtifactGroupField, JvmArtifactArtifactField))
    ]

    artifact_mapping: dict[UnversionedCoordinate, set[Address]] = defaultdict(set)
    for tgt in jvm_artifact_targets:
        group = tgt[JvmArtifactGroupField].value
        if not group:
            raise ValueError(
                f"The {JvmArtifactGroupField.alias} field of target {tgt.address} must be set."
            )

        artifact = tgt[JvmArtifactArtifactField].value
        if not artifact:
            raise ValueError(
                f"The {JvmArtifactArtifactField.alias} field of target {tgt.address} must be set."
            )

        key = UnversionedCoordinate(group=group, artifact=artifact)
        artifact_mapping[key].add(tgt.address)

    return AvailableThirdPartyArtifacts(
        FrozenDict({key: FrozenOrderedSet(value) for key, value in artifact_mapping.items()})
    )


@rule
async def compute_java_third_party_artifact_mapping(
    java_infer_subsystem: JavaInferSubsystem,
) -> ThirdPartyJavaPackageToArtifactMapping:
    def insert(mapping: dict, imp: str, value: Any) -> None:
        imp_parts = imp.split(".")
        current_node = mapping
        for imp_part in imp_parts[0:-1]:
            if imp_part not in current_node:
                current_node[imp_part] = {}
            elif isinstance(current_node[imp_part], str):
                # Existing node is a string. Convert it to a dict with default key set.
                existing_value = current_node[imp_part]
                current_node[imp_part] = {
                    jvm_artifact_mappings.DEFAULT: existing_value,
                }
            current_node = current_node[imp_part]

        final_imp_part = imp_parts[-1]
        if final_imp_part in current_node:
            raise ValueError(
                f"There is a conflicting entry in the third-party Java package mapping for `{imp}`. "
                f"The existing entry is `{current_node[final_imp_part]}`. "
                f"The conflicting entry is `{value}`."
            )
        current_node[final_imp_part] = value

    def freeze(d: dict) -> FrozenDict[Any, Any]:
        result = {}
        for k, v in d.items():
            result[k] = freeze(v) if isinstance(v, dict) else v
        return FrozenDict(result)

    mapping: dict[Any, Any] = {}
    for imp_name, imp_action in java_infer_subsystem.third_party_import_mapping.items():
        value = (
            UnversionedCoordinate.from_coord_str(imp_action)
            if imp_action != "SKIP"
            else jvm_artifact_mappings.SKIP
        )
        insert(mapping, imp_name, value)

    return ThirdPartyJavaPackageToArtifactMapping(freeze(mapping))


def find_artifact_mapping(
    imp: str, mapping: ThirdPartyJavaPackageToArtifactMapping
) -> UnversionedCoordinate | None:
    imp_parts = imp.split(".")
    current_node: Any = mapping.mapping

    for imp_part in imp_parts:
        # If the current node is not searchable, then return None since there is no way to
        # continue the search.
        if not isinstance(current_node, FrozenDict):
            return None

        # If the package component is missing from the dictionary, then the search has failed.
        if imp_part not in current_node:
            if "*" in current_node:
                # Unless there is a "*" key which matches any symbol.
                # TODO: Consider how we want to do partial package matches.
                imp_part = "*"
            else:
                return None

        # Otherwise, use the node that has been found as the next node of the search.
        current_node = current_node[imp_part]

    # The search fails if the SKIP direction was found.
    if current_node is jvm_artifact_mappings.SKIP:
        return None

    # Extract any default entry if the candidate is a dictionary with a DEFAULT key.
    if isinstance(current_node, FrozenDict) and jvm_artifact_mappings.DEFAULT in current_node:
        current_node = current_node[jvm_artifact_mappings.DEFAULT]

    if isinstance(current_node, UnversionedCoordinate):
        return current_node
    else:
        raise ValueError(
            f"Illegal state: The state computed from --java-infer-third-party-import-mapping contained an "
            f"unexpected value: {current_node}"
        )


@rule(desc="Inferring Java dependencies by analyzing consumed and top-level types")
async def infer_java_dependencies_via_third_party_imports(
    request: InferJavaThirdPartyImportDependencies,
    java_infer_subsystem: JavaInferSubsystem,
    available_artifacts: AvailableThirdPartyArtifacts,
    artifact_package_mapping: ThirdPartyJavaPackageToArtifactMapping,
) -> InferredDependencies:
    if not java_infer_subsystem.third_party_imports:
        return InferredDependencies([])

    address = request.sources_field.address
    wrapped_tgt = await Get(WrappedTarget, Address, address)
    explicitly_provided_deps, analysis = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(wrapped_tgt.target[Dependencies])),
        Get(JavaSourceDependencyAnalysis, SourceFilesRequest([request.sources_field])),
    )

    dependencies: OrderedSet[Address] = OrderedSet()

    for imp in analysis.imports:
        artifact_mapping_opt = find_artifact_mapping(imp.name, artifact_package_mapping)
        if not artifact_mapping_opt:
            continue

        candidate_artifact_addresses = available_artifacts.artifacts.get(artifact_mapping_opt)
        if not candidate_artifact_addresses:
            continue

        explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
            candidate_artifact_addresses,
            address,
            import_reference="third-party package",
            context=f"The target {address} imports `{imp.name}`",
        )

        maybe_disambiguated = explicitly_provided_deps.disambiguated(candidate_artifact_addresses)
        if maybe_disambiguated:
            dependencies.add(maybe_disambiguated)

    return InferredDependencies(dependencies)


def rules():
    return [
        *collect_rules(),
        *java_parser.rules(),
        *import_parser.rules(),
        *package_mapper.rules(),
        *source_files_rules(),
        UnionRule(InferDependenciesRequest, InferJavaSourceDependencies),
        UnionRule(InferDependenciesRequest, InferJavaThirdPartyImportDependencies),
    ]
