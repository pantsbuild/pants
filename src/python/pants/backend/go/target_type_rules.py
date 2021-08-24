# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.go import import_analysis, pkg
from pants.backend.go.import_analysis import ResolvedImportPathsForGoLangDistribution
from pants.backend.go.module import FindNearestGoModuleRequest, ResolvedOwningGoModule
from pants.backend.go.pkg import (
    ResolvedGoPackage,
    ResolveExternalGoPackageRequest,
    ResolveGoPackageRequest,
)
from pants.backend.go.target_types import (
    GoExtModPackageDependencies,
    GoImportPath,
    GoPackageDependencies,
    GoPackageSources,
)
from pants.base.specs import (
    AddressSpecs,
    DescendantAddresses,
    MaybeEmptyDescendantAddresses,
    MaybeEmptySiblingAddresses,
)
from pants.build_graph.address import Address
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    InferDependenciesRequest,
    InferredDependencies,
    InjectDependenciesRequest,
    InjectedDependencies,
    Targets,
)
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict

logger = logging.getLogger(__name__)


# Inject a dependency between a go_package and its owning go_module.
class InjectGoPackageDependenciesRequest(InjectDependenciesRequest):
    inject_for = GoPackageDependencies


@rule
async def inject_go_package_dependencies(
    request: InjectGoPackageDependenciesRequest,
) -> InjectedDependencies:
    owning_go_module_result = await Get(
        ResolvedOwningGoModule,
        FindNearestGoModuleRequest(request.dependencies_field.address.spec_path),
    )
    if owning_go_module_result.module_address:
        return InjectedDependencies([owning_go_module_result.module_address])
    else:
        return InjectedDependencies()


# TODO: Figure out how to merge (or not) this with ResolvedImportPaths as a base class.
@dataclass(frozen=True)
class GoImportPathToPackageMapping:
    # Maps import paths to the address of go_package or (more likely) _go_ext_mod_package targets.
    mapping: FrozenDict[str, tuple[Address, ...]]


@rule
async def analyze_import_path_to_package_mapping() -> GoImportPathToPackageMapping:
    mapping: dict[str, list[Address]] = {}

    all_targets = await Get(Targets, AddressSpecs([DescendantAddresses("")]))
    for tgt in all_targets:
        if not tgt.has_field(GoImportPath):
            continue

        # Note: This will usually skip go_package targets since they need analysis to infer the import path
        # since there is no way in the engine to attach inferred values as fields.
        import_path = tgt[GoImportPath].value
        if not import_path:
            continue

        if import_path not in mapping:
            mapping[import_path] = []
        mapping[import_path].append(tgt.address)

    frozen_mapping = FrozenDict({ip: tuple(tgts) for ip, tgts in mapping.items()})
    return GoImportPathToPackageMapping(mapping=frozen_mapping)


class InferGoPackageDependenciesRequest(InferDependenciesRequest):
    infer_from = GoPackageSources


# TODO: Refactor this rule so as much as possible is memoized by invoking other rules. Consider
# for example `FirstPartyPythonModuleMapping` and `ThirdPartyPythonModuleMapping`.
@rule
async def infer_go_dependencies(
    request: InferGoPackageDependenciesRequest,
    goroot_imports: ResolvedImportPathsForGoLangDistribution,
    package_mapping: GoImportPathToPackageMapping,
) -> InferredDependencies:
    this_go_package = await Get(
        ResolvedGoPackage, ResolveGoPackageRequest(request.sources_field.address)
    )

    # Obtain all go_package targets under this package's go_module.
    assert this_go_package.module_address is not None
    spec_path = this_go_package.module_address.spec_path
    address_specs = [
        MaybeEmptySiblingAddresses(spec_path),
        MaybeEmptyDescendantAddresses(spec_path),
    ]
    candidate_targets = await Get(Targets, AddressSpecs(address_specs))
    go_package_targets = [
        tgt
        for tgt in candidate_targets
        if tgt.has_field(GoPackageSources) and tgt.address != this_go_package.address
    ]

    # Resolve all of the packages found.
    first_party_import_path_to_address = {}
    first_party_go_packages = await MultiGet(
        Get(ResolvedGoPackage, ResolveGoPackageRequest(tgt.address)) for tgt in go_package_targets
    )
    for first_party_go_package in first_party_go_packages:
        # Skip packages that are not part of this package's module.
        # TODO: This requires that all first-party code in the monorepo be part of the same go_module. Will need
        # figure out how multiple modules in a monorepo can interact.
        if first_party_go_package.module_address != this_go_package.module_address:
            continue

        address = first_party_go_package.address
        if not address:
            continue

        first_party_import_path_to_address[first_party_go_package.import_path] = address

    # Loop through all of the imports of this package and add dependencies on other packages and
    # external modules.
    inferred_dependencies = []
    for import_path in this_go_package.imports + this_go_package.test_imports:
        # Check whether the import path comes from the standard library.
        if import_path in goroot_imports.import_path_mapping:
            continue

        # Infer first-party dependencies to other packages in same go_module.
        if import_path in first_party_import_path_to_address:
            inferred_dependencies.append(first_party_import_path_to_address[import_path])
            continue

        # Infer third-party dependencies on _go_ext_mod_package targets.
        candidate_third_party_packages = package_mapping.mapping.get(import_path, ())
        if len(candidate_third_party_packages) > 1:
            logger.warning(
                f"Ambiguous mapping for import path {import_path} on packages at addresses: {candidate_third_party_packages}"
            )
        elif len(candidate_third_party_packages) == 1:
            inferred_dependencies.append(candidate_third_party_packages[0])
        else:
            logger.debug(
                f"Unable to infer dependency for import path '{import_path}' "
                f"in go_package at address '{this_go_package.address}'."
            )

    return InferredDependencies(inferred_dependencies, sibling_dependencies_inferrable=False)


class InjectGoExternalPackageDependenciesRequest(InjectDependenciesRequest):
    inject_for = GoExtModPackageDependencies


# TODO: This duplicates first-party dependency inference but that other rule cannot operate on _go_ext_mod_package
# targets since there is no sources field in a _go_ext_mod_package. Consider how to merge the inference/injection
# rules into one.
@rule
async def inject_go_external_package_dependencies(
    request: InjectGoExternalPackageDependenciesRequest,
    goroot_imports: ResolvedImportPathsForGoLangDistribution,
    package_mapping: GoImportPathToPackageMapping,
) -> InjectedDependencies:
    this_go_package = await Get(
        ResolvedGoPackage, ResolveExternalGoPackageRequest(request.dependencies_field.address)
    )

    # Loop through all of the imports of this package and add dependencies on other packages and
    # external modules.
    inferred_dependencies = []
    for import_path in this_go_package.imports + this_go_package.test_imports:
        # Check whether the import path comes from the standard library.
        if import_path in goroot_imports.import_path_mapping:
            continue

        # Infer third-party dependencies on _go_ext_mod_package targets.
        candidate_third_party_packages = package_mapping.mapping.get(import_path, ())
        if len(candidate_third_party_packages) > 1:
            logger.warning(
                f"Ambiguous mapping for import path {import_path} on packages at addresses: {candidate_third_party_packages}"
            )
        elif len(candidate_third_party_packages) == 1:
            inferred_dependencies.append(candidate_third_party_packages[0])
        else:
            logger.debug(
                f"Unable to infer dependency for import path '{import_path}' "
                f"in _go_ext_mod_package at address '{this_go_package.address}'."
            )

    return InjectedDependencies(inferred_dependencies)


def rules():
    return (
        *collect_rules(),
        *pkg.rules(),
        *import_analysis.rules(),
        UnionRule(InjectDependenciesRequest, InjectGoPackageDependenciesRequest),
        UnionRule(InferDependenciesRequest, InferGoPackageDependenciesRequest),
        UnionRule(InjectDependenciesRequest, InjectGoExternalPackageDependenciesRequest),
    )
