# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging

from pants.backend.go import import_analysis, pkg
from pants.backend.go.import_analysis import ResolvedImportPathsForGoLangDistribution
from pants.backend.go.module import FindNearestGoModuleRequest, ResolvedOwningGoModule
from pants.backend.go.pkg import ResolvedGoPackage, ResolveGoPackageRequest
from pants.backend.go.target_types import GoPackageDependencies, GoPackageSources
from pants.base.specs import AddressSpecs, MaybeEmptyDescendantAddresses, MaybeEmptySiblingAddresses
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    InferDependenciesRequest,
    InferredDependencies,
    InjectDependenciesRequest,
    InjectedDependencies,
    UnexpandedTargets,
)
from pants.engine.unions import UnionRule

logger = logging.getLogger(__name__)


class InjectGoModuleDependency(InjectDependenciesRequest):
    inject_for = GoPackageDependencies


@rule
async def inject_go_module_dependency(request: InjectGoModuleDependency) -> InjectedDependencies:
    owning_go_module_result = await Get(
        ResolvedOwningGoModule,
        FindNearestGoModuleRequest(request.dependencies_field.address.spec_path),
    )
    if owning_go_module_result.module_address:
        return InjectedDependencies([owning_go_module_result.module_address])
    else:
        return InjectedDependencies()


class InferGoDependenciesRequest(InferDependenciesRequest):
    infer_from = GoPackageSources


@rule
async def infer_go_dependencies(
    request: InferGoDependenciesRequest, goroot_imports: ResolvedImportPathsForGoLangDistribution
) -> InferredDependencies:
    this_go_package = await Get(
        ResolvedGoPackage, ResolveGoPackageRequest(request.sources_field.address)
    )
    print(f"resolved_go_package={this_go_package}")

    # Obtain all go_package targets under this package's go_module.
    spec_path = this_go_package.module_address.spec_path
    address_specs = [
        MaybeEmptySiblingAddresses(spec_path),
        MaybeEmptyDescendantAddresses(spec_path),
    ]
    candidate_targets = await Get(UnexpandedTargets, AddressSpecs(address_specs))
    go_package_targets = [
        tgt
        for tgt in candidate_targets
        if tgt.has_field(GoPackageSources)
        and not tgt.address.is_file_target
        and tgt.address != this_go_package.address
    ]
    print(f"go_package_targets={go_package_targets}")

    # Resolve all of the packages found.
    import_path_to_pkg_address = {}
    resolved_go_packages = await MultiGet(
        Get(ResolvedGoPackage, ResolveGoPackageRequest(tgt.address)) for tgt in go_package_targets
    )
    print(f"resolved_go_packages={resolved_go_packages}")
    for pkg in resolved_go_packages:
        # Skip packages that are not part of this package's module.
        # TODO: This requires that all first-party code in the monorepo be part of the same go_module. Will need
        # figure out how multiple modules in a monorepo can interact.
        if pkg.module_address != this_go_package.module_address:
            print(
                f"Skipping addr={pkg.address} (mod_addr={pkg.module_address}, this_mod_addr={this_go_package.module_address})"
            )
            continue

        import_path_to_pkg_address[pkg.import_path] = pkg.address

    print(f"import_path_to_pkg_address={import_path_to_pkg_address}")

    # Loop through all of the imports of this package and add dependencies on other packages automatically.
    inferred_dependencies = []
    for import_path in this_go_package.imports + this_go_package.test_imports:
        # Check whether the import path comes from the standard library.
        if import_path in goroot_imports.import_path_mapping:
            continue

        # Otherwise check whether the import comes from other packages in this module.
        if import_path in import_path_to_pkg_address:
            inferred_dependencies.append(import_path_to_pkg_address[import_path])
        else:
            raise ValueError(
                f"Unable to infer dependency for import path {import_path} "
                f"in go_package at address '{this_go_package.address}'"
            )

    return InferredDependencies(inferred_dependencies, sibling_dependencies_inferrable=False)


def rules():
    return (
        *collect_rules(),
        *pkg.rules(),
        *import_analysis.rules(),
        UnionRule(InjectDependenciesRequest, InjectGoModuleDependency),
        UnionRule(InferDependenciesRequest, InferGoDependenciesRequest),
    )
