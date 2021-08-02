# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging

from pants.backend.go import import_analysis, pkg
from pants.backend.go.import_analysis import ResolvedImportPathsForGoLangDistribution
from pants.backend.go.module import (
    FindNearestGoModuleRequest,
    ResolvedGoModule,
    ResolvedOwningGoModule,
    ResolveGoModuleRequest,
)
from pants.backend.go.pkg import ResolvedGoPackage, ResolveGoPackageRequest
from pants.backend.go.target_types import (
    GoExternalModule,
    GoImportPath,
    GoModuleDependencies,
    GoPackageDependencies,
    GoPackageSources,
)
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


# Inject dependencies from a go_module to any referenced go_external_module targets.
class InjectGoModuleDependenciesRequest(InjectDependenciesRequest):
    inject_for = GoModuleDependencies


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

    # TODO: Use MultiGet if possible to process modules concurrently.
    resolved_go_module = await Get(
        ResolvedGoModule, ResolveGoModuleRequest(this_go_package.module_address)
    )

    # Find all go_external_modules in the repo and map their import paths to their address.
    candidate_go_external_module_targets = await Get(
        UnexpandedTargets, AddressSpecs([MaybeEmptyDescendantAddresses("")])
    )
    go_external_module_targets = [
        tgt for tgt in candidate_go_external_module_targets if isinstance(tgt, GoExternalModule)
    ]
    third_party_import_path_to_address = {
        tgt[GoImportPath].value: tgt.address for tgt in go_external_module_targets
    }
    print(f"third_party_import_path_to_address={third_party_import_path_to_address}")

    # Resolve all of the packages found.
    first_party_import_path_to_address = {}
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

        first_party_import_path_to_address[pkg.import_path] = pkg.address

    print(f"first_party_import_path_to_address={first_party_import_path_to_address}")

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

        # Infer third-party dependencies on go_external_module targets.
        found_module_import = False
        for module_import_path, address in third_party_import_path_to_address.items():
            # TODO: This check naively assumes that the import path for the external module is a prefix of any package
            # from the external module and that the import path will never overlap with another external module's
            # import path. This may be the case, but bears investigation. One problem could be how to handle multiple
            # major versions which have separate import paths.
            print(f"module_import_path='{module_import_path}'\nimport_path='{import_path}'")
            if import_path.startswith(module_import_path):
                inferred_dependencies.append(address)
                found_module_import = True

        if found_module_import:
            continue

        raise ValueError(
            f"Unable to infer dependency for import path '{import_path}' "
            f"in go_package at address '{this_go_package.address}'."
        )

    return InferredDependencies(inferred_dependencies, sibling_dependencies_inferrable=False)


def rules():
    return (
        *collect_rules(),
        *pkg.rules(),
        *import_analysis.rules(),
        UnionRule(InjectDependenciesRequest, InjectGoPackageDependenciesRequest),
        UnionRule(InferDependenciesRequest, InferGoDependenciesRequest),
    )
