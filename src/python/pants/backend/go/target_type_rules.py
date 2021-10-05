# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

from pants.backend.go.target_types import (
    GoBinaryDependenciesField,
    GoBinaryMainPackage,
    GoBinaryMainPackageField,
    GoBinaryMainPackageRequest,
    GoExternalModulePathField,
    GoExternalModuleVersionField,
    GoExternalPackageDependencies,
    GoExternalPackageImportPathField,
    GoExternalPackageTarget,
    GoImportPath,
    GoModTarget,
    GoPackageDependencies,
    GoPackageSources,
)
from pants.backend.go.util_rules import go_pkg, import_analysis
from pants.backend.go.util_rules.external_module import (
    ExternalModulePkgImportPaths,
    ExternalModulePkgImportPathsRequest,
    ResolveExternalGoPackageRequest,
)
from pants.backend.go.util_rules.go_mod import (
    GoModInfo,
    GoModInfoRequest,
    ModuleDescriptor,
    OwningGoMod,
    OwningGoModRequest,
)
from pants.backend.go.util_rules.go_pkg import ResolvedGoPackage, ResolveGoPackageRequest
from pants.backend.go.util_rules.import_analysis import GoStdLibImports
from pants.base.exceptions import ResolveError
from pants.base.specs import (
    AddressSpecs,
    DescendantAddresses,
    MaybeEmptyDescendantAddresses,
    MaybeEmptySiblingAddresses,
    SiblingAddresses,
)
from pants.engine.addresses import Address, AddressInput
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    GeneratedTargets,
    GenerateTargetsRequest,
    InferDependenciesRequest,
    InferredDependencies,
    InjectDependenciesRequest,
    InjectedDependencies,
    InvalidFieldException,
    Targets,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


# Inject a dependency between a go_package and its owning go_mod.
class InjectGoPackageDependenciesRequest(InjectDependenciesRequest):
    inject_for = GoPackageDependencies


@rule
async def inject_go_package_dependencies(
    request: InjectGoPackageDependenciesRequest,
) -> InjectedDependencies:
    owning_go_mod = await Get(OwningGoMod, OwningGoModRequest(request.dependencies_field.address))
    return InjectedDependencies([owning_go_mod.address])


# TODO: Figure out how to merge (or not) this with ResolvedImportPaths as a base class.
@dataclass(frozen=True)
class GoImportPathToPackageMapping:
    # Maps import paths to the address of go_package or (more likely) go_external_package targets.
    mapping: FrozenDict[str, tuple[Address, ...]]


@rule
async def analyze_import_path_to_package_mapping() -> GoImportPathToPackageMapping:
    mapping: dict[str, list[Address]] = defaultdict(list)

    all_targets = await Get(Targets, AddressSpecs([DescendantAddresses("")]))
    for tgt in all_targets:
        if not tgt.has_field(GoImportPath):
            continue

        # Note: This will usually skip go_package targets since they need analysis to infer the import path
        # since there is no way in the engine to attach inferred values as fields.
        import_path = tgt[GoImportPath].value
        if not import_path:
            continue

        mapping[import_path].append(tgt.address)

    frozen_mapping = FrozenDict({ip: tuple(tgts) for ip, tgts in mapping.items()})
    return GoImportPathToPackageMapping(mapping=frozen_mapping)


class InferGoPackageDependenciesRequest(InferDependenciesRequest):
    infer_from = GoPackageSources


# TODO(12761): Refactor this rule so as much as possible is memoized by invoking other rules. Consider
# for example `FirstPartyPythonModuleMapping` and `ThirdPartyPythonModuleMapping`.
@rule
async def infer_go_dependencies(
    request: InferGoPackageDependenciesRequest,
    std_lib_imports: GoStdLibImports,
    package_mapping: GoImportPathToPackageMapping,
) -> InferredDependencies:
    this_go_package = await Get(
        ResolvedGoPackage, ResolveGoPackageRequest(request.sources_field.address)
    )

    # Obtain all go_package targets under this package's go_mod.
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
        # TODO: This requires that all first-party code in the monorepo be part of the same go_mod. Will need
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
        if import_path in std_lib_imports:
            continue

        # Infer first-party dependencies to other packages in same go_mod.
        if import_path in first_party_import_path_to_address:
            inferred_dependencies.append(first_party_import_path_to_address[import_path])
            continue

        # Infer third-party dependencies on _go_external_package targets.
        candidate_third_party_packages = package_mapping.mapping.get(import_path, ())
        if len(candidate_third_party_packages) > 1:
            # TODO: Use ExplicitlyProvidedDependencies.maybe_warn_of_ambiguous_dependency_inference standard
            # way of doing disambiguation.
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

    return InferredDependencies(inferred_dependencies)


class InjectGoExternalPackageDependenciesRequest(InjectDependenciesRequest):
    inject_for = GoExternalPackageDependencies


# TODO(#12761): This duplicates first-party dependency inference but that other rule cannot operate
#  on _go_external_package targets since there is no sources field in a _go_external_package.
#  Consider how to merge the inference/injection rules into one. Maybe use a private Sources field?
@rule
async def inject_go_external_package_dependencies(
    request: InjectGoExternalPackageDependenciesRequest,
    std_lib_imports: GoStdLibImports,
    package_mapping: GoImportPathToPackageMapping,
) -> InjectedDependencies:
    wrapped_target = await Get(WrappedTarget, Address, request.dependencies_field.address)
    tgt = wrapped_target.target
    assert isinstance(tgt, GoExternalPackageTarget)

    owning_go_mod = await Get(OwningGoMod, OwningGoModRequest(tgt.address))
    go_mod_info = await Get(GoModInfo, GoModInfoRequest(owning_go_mod.address))

    this_go_package = await Get(
        ResolvedGoPackage, ResolveExternalGoPackageRequest(tgt, go_mod_info.stripped_digest)
    )

    # Loop through all of the imports of this package and add dependencies on other packages and
    # external modules.
    inferred_dependencies = []
    for import_path in this_go_package.imports + this_go_package.test_imports:
        if import_path in std_lib_imports:
            continue

        # Infer third-party dependencies on _go_external_package targets.
        candidate_third_party_packages = package_mapping.mapping.get(import_path, ())
        if len(candidate_third_party_packages) > 1:
            # TODO: Use ExplicitlyProvidedDependencies.maybe_warn_of_ambiguous_dependency_inference standard
            # way of doing disambiguation.
            logger.warning(
                f"Ambiguous mapping for import path {import_path} on packages at addresses: {candidate_third_party_packages}"
            )
        elif len(candidate_third_party_packages) == 1:
            inferred_dependencies.append(candidate_third_party_packages[0])
        else:
            logger.debug(
                f"Unable to infer dependency for import path '{import_path}' "
                f"in go_external_package at address '{this_go_package.address}'."
            )

    return InjectedDependencies(inferred_dependencies)


# -----------------------------------------------------------------------------------------------
# Generate `_go_external_package` targets
# -----------------------------------------------------------------------------------------------


class GenerateGoExternalPackageTargetsRequest(GenerateTargetsRequest):
    generate_from = GoModTarget


@rule(desc="Generate targets for each external package in `go.mod`", level=LogLevel.DEBUG)
async def generate_go_external_package_targets(
    request: GenerateGoExternalPackageTargetsRequest,
) -> GeneratedTargets:
    generator_addr = request.generator.address
    go_mod_info = await Get(GoModInfo, GoModInfoRequest(generator_addr))
    all_pkg_import_paths = await MultiGet(
        Get(
            ExternalModulePkgImportPaths,
            ExternalModulePkgImportPathsRequest(
                module_path=module_descriptor.path,
                version=module_descriptor.version,
                go_mod_stripped_digest=go_mod_info.stripped_digest,
            ),
        )
        for module_descriptor in go_mod_info.modules
    )

    def create_tgt(
        module_descriptor: ModuleDescriptor, pkg_import_path: str
    ) -> GoExternalPackageTarget:
        return GoExternalPackageTarget(
            {
                GoExternalModulePathField.alias: module_descriptor.path,
                GoExternalModuleVersionField.alias: module_descriptor.version,
                GoExternalPackageImportPathField.alias: pkg_import_path,
            },
            # E.g. `src/go:mod#github.com/google/uuid`.
            Address(
                generator_addr.spec_path,
                target_name=generator_addr.target_name,
                generated_name=pkg_import_path,
            ),
        )

    return GeneratedTargets(
        request.generator,
        (
            create_tgt(module_descriptor, pkg_import_path)
            for module_descriptor, pkg_import_paths in zip(
                go_mod_info.modules, all_pkg_import_paths
            )
            for pkg_import_path in pkg_import_paths
        ),
    )


# -----------------------------------------------------------------------------------------------
# The `main` field for `go_binary`
# -----------------------------------------------------------------------------------------------


@rule
async def determine_main_pkg_for_go_binary(
    request: GoBinaryMainPackageRequest,
) -> GoBinaryMainPackage:
    addr = request.field.address
    if request.field.value:
        wrapped_specified_tgt = await Get(
            WrappedTarget,
            AddressInput,
            AddressInput.parse(request.field.value, relative_to=addr.spec_path),
        )
        if not wrapped_specified_tgt.target.has_field(GoPackageSources):
            raise InvalidFieldException(
                f"The {repr(GoBinaryMainPackageField.alias)} field in target {addr} must point to "
                "a `go_package` target, but was the address for a "
                f"`{wrapped_specified_tgt.target.alias}` target.\n\n"
                "Hint: consider leaving off this field so that Pants will find the `go_package` "
                "target for you."
            )
        return GoBinaryMainPackage(wrapped_specified_tgt.target.address)

    build_dir_targets = await Get(Targets, AddressSpecs([SiblingAddresses(addr.spec_path)]))
    internal_pkg_targets = [tgt for tgt in build_dir_targets if tgt.has_field(GoPackageSources)]
    if len(internal_pkg_targets) == 1:
        return GoBinaryMainPackage(internal_pkg_targets[0].address)

    wrapped_tgt = await Get(WrappedTarget, Address, addr)
    alias = wrapped_tgt.target.alias
    if not internal_pkg_targets:
        raise ResolveError(
            f"The `{alias}` target {addr} requires that there is a `go_package` "
            "target in the same directory, but none were found."
        )
    raise ResolveError(
        f"There are multiple `go_package` targets in the same directory of the `{alias}` "
        f"target {addr}, so it is ambiguous what to use as the `main` package.\n\n"
        f"To fix, please either set the `main` field for `{addr} or remove these "
        "`go_package` targets so that only one remains: "
        f"{sorted(tgt.address.spec for tgt in internal_pkg_targets)}"
    )


class InjectGoBinaryMainDependencyRequest(InjectDependenciesRequest):
    inject_for = GoBinaryDependenciesField


@rule
async def inject_go_binary_main_dependency(
    request: InjectGoBinaryMainDependencyRequest,
) -> InjectedDependencies:
    wrapped_tgt = await Get(WrappedTarget, Address, request.dependencies_field.address)
    main_pkg = await Get(
        GoBinaryMainPackage,
        GoBinaryMainPackageRequest(wrapped_tgt.target[GoBinaryMainPackageField]),
    )
    return InjectedDependencies([main_pkg.address])


def rules():
    return (
        *collect_rules(),
        *go_pkg.rules(),
        *import_analysis.rules(),
        UnionRule(InjectDependenciesRequest, InjectGoPackageDependenciesRequest),
        UnionRule(InferDependenciesRequest, InferGoPackageDependenciesRequest),
        UnionRule(InjectDependenciesRequest, InjectGoExternalPackageDependenciesRequest),
        UnionRule(InjectDependenciesRequest, InjectGoBinaryMainDependencyRequest),
        UnionRule(GenerateTargetsRequest, GenerateGoExternalPackageTargetsRequest),
    )
