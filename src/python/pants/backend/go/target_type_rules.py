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
    GoImportPathField,
    GoModTarget,
    GoPackageSourcesField,
    GoThirdPartyPackageDependenciesField,
    GoThirdPartyPackageTarget,
)
from pants.backend.go.util_rules import first_party_pkg, import_analysis
from pants.backend.go.util_rules.first_party_pkg import (
    FallibleFirstPartyPkgAnalysis,
    FirstPartyPkgAnalysisRequest,
    FirstPartyPkgImportPath,
    FirstPartyPkgImportPathRequest,
)
from pants.backend.go.util_rules.go_mod import GoModInfo, GoModInfoRequest
from pants.backend.go.util_rules.import_analysis import GoStdLibImports
from pants.backend.go.util_rules.third_party_pkg import (
    AllThirdPartyPackages,
    AllThirdPartyPackagesRequest,
    ThirdPartyPkgInfo,
    ThirdPartyPkgInfoRequest,
)
from pants.base.exceptions import ResolveError
from pants.base.specs import AddressSpecs, SiblingAddresses
from pants.engine.addresses import Address, AddressInput
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    AllTargets,
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
from pants.engine.unions import UnionMembership, UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class AllGoTargets(Targets):
    pass


@rule(desc="Find all Go targets in project", level=LogLevel.DEBUG)
def find_all_go_targets(tgts: AllTargets) -> AllGoTargets:
    return AllGoTargets(
        t for t in tgts if t.has_field(GoImportPathField) or t.has_field(GoPackageSourcesField)
    )


@dataclass(frozen=True)
class ImportPathToPackages:
    mapping: FrozenDict[str, tuple[Address, ...]]


@rule(desc="Map all Go targets to their import paths", level=LogLevel.DEBUG)
async def map_import_paths_to_packages(go_tgts: AllGoTargets) -> ImportPathToPackages:
    mapping: dict[str, list[Address]] = defaultdict(list)
    first_party_addresses = []
    first_party_gets = []
    for tgt in go_tgts:
        if tgt.has_field(GoImportPathField):
            import_path = tgt[GoImportPathField].value
            mapping[import_path].append(tgt.address)
        else:
            first_party_addresses.append(tgt.address)
            first_party_gets.append(
                Get(FirstPartyPkgImportPath, FirstPartyPkgImportPathRequest(tgt.address))
            )

    first_party_import_paths = await MultiGet(first_party_gets)
    for import_path_info, addr in zip(first_party_import_paths, first_party_addresses):
        mapping[import_path_info.import_path].append(addr)

    frozen_mapping = FrozenDict({ip: tuple(tgts) for ip, tgts in mapping.items()})
    return ImportPathToPackages(frozen_mapping)


class InferGoPackageDependenciesRequest(InferDependenciesRequest):
    infer_from = GoPackageSourcesField


@rule(desc="Infer dependencies for first-party Go packages", level=LogLevel.DEBUG)
async def infer_go_dependencies(
    request: InferGoPackageDependenciesRequest,
    std_lib_imports: GoStdLibImports,
    package_mapping: ImportPathToPackages,
) -> InferredDependencies:
    addr = request.sources_field.address
    maybe_pkg_analysis = await Get(
        FallibleFirstPartyPkgAnalysis, FirstPartyPkgAnalysisRequest(addr)
    )
    if maybe_pkg_analysis.analysis is None:
        logger.error(
            f"Failed to analyze {maybe_pkg_analysis.import_path} for dependency inference:\n"
            f"{maybe_pkg_analysis.stderr}"
        )
        return InferredDependencies([])
    pkg_analysis = maybe_pkg_analysis.analysis

    inferred_dependencies = []
    for import_path in (
        *pkg_analysis.imports,
        *pkg_analysis.test_imports,
        *pkg_analysis.xtest_imports,
    ):
        if import_path in std_lib_imports:
            continue
        # Avoid a dependency cycle caused by external test imports of this package (i.e., "xtest").
        if import_path == pkg_analysis.import_path:
            continue
        candidate_packages = package_mapping.mapping.get(import_path, ())
        if len(candidate_packages) > 1:
            # TODO(#12761): Use ExplicitlyProvidedDependencies for disambiguation.
            logger.warning(
                f"Ambiguous mapping for import path {import_path} on packages at addresses: {candidate_packages}"
            )
        elif len(candidate_packages) == 1:
            inferred_dependencies.append(candidate_packages[0])
        else:
            logger.debug(
                f"Unable to infer dependency for import path '{import_path}' "
                f"in go_package at address '{addr}'."
            )

    return InferredDependencies(inferred_dependencies)


class InjectGoThirdPartyPackageDependenciesRequest(InjectDependenciesRequest):
    inject_for = GoThirdPartyPackageDependenciesField


@rule(desc="Infer dependencies for third-party Go packages", level=LogLevel.DEBUG)
async def inject_go_third_party_package_dependencies(
    request: InjectGoThirdPartyPackageDependenciesRequest,
    std_lib_imports: GoStdLibImports,
    package_mapping: ImportPathToPackages,
) -> InjectedDependencies:
    addr = request.dependencies_field.address
    go_mod_address = addr.maybe_convert_to_target_generator()
    wrapped_target, go_mod_info = await MultiGet(
        Get(WrappedTarget, Address, addr),
        Get(GoModInfo, GoModInfoRequest(go_mod_address)),
    )
    tgt = wrapped_target.target
    pkg_info = await Get(
        ThirdPartyPkgInfo,
        ThirdPartyPkgInfoRequest(
            tgt[GoImportPathField].value, go_mod_info.digest, go_mod_info.mod_path
        ),
    )

    inferred_dependencies = []
    for import_path in pkg_info.imports:
        if import_path in std_lib_imports:
            continue

        candidate_packages = package_mapping.mapping.get(import_path, ())
        if len(candidate_packages) > 1:
            # TODO(#12761): Use ExplicitlyProvidedDependencies for disambiguation.
            logger.warning(
                f"Ambiguous mapping for import path {import_path} on packages at addresses: {candidate_packages}"
            )
        elif len(candidate_packages) == 1:
            inferred_dependencies.append(candidate_packages[0])
        else:
            logger.debug(
                f"Unable to infer dependency for import path '{import_path}' "
                f"in go_third_party_package at address '{addr}'."
            )

    return InjectedDependencies(inferred_dependencies)


# -----------------------------------------------------------------------------------------------
# Generate `go_third_party_package` targets
# -----------------------------------------------------------------------------------------------


class GenerateTargetsFromGoModRequest(GenerateTargetsRequest):
    generate_from = GoModTarget


@rule(desc="Generate `go_third_party_package` targets from `go_mod` target", level=LogLevel.DEBUG)
async def generate_targets_from_go_mod(
    request: GenerateTargetsFromGoModRequest,
    union_membership: UnionMembership,
) -> GeneratedTargets:
    generator_addr = request.generator.address
    go_mod_info = await Get(GoModInfo, GoModInfoRequest(generator_addr))
    all_packages = await Get(
        AllThirdPartyPackages,
        AllThirdPartyPackagesRequest(go_mod_info.digest, go_mod_info.mod_path),
    )

    def create_tgt(pkg_info: ThirdPartyPkgInfo) -> GoThirdPartyPackageTarget:
        return GoThirdPartyPackageTarget(
            {GoImportPathField.alias: pkg_info.import_path},
            # E.g. `src/go:mod#github.com/google/uuid`.
            generator_addr.create_generated(pkg_info.import_path),
            union_membership,
            residence_dir=generator_addr.spec_path,
        )

    return GeneratedTargets(
        request.generator,
        (create_tgt(pkg_info) for pkg_info in all_packages.import_paths_to_pkg_info.values()),
    )


# -----------------------------------------------------------------------------------------------
# The `main` field for `go_binary`
# -----------------------------------------------------------------------------------------------


@rule(desc="Determine first-party package used by `go_binary` target", level=LogLevel.DEBUG)
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
        if not wrapped_specified_tgt.target.has_field(GoPackageSourcesField):
            raise InvalidFieldException(
                f"The {repr(GoBinaryMainPackageField.alias)} field in target {addr} must point to "
                "a `go_package` target, but was the address for a "
                f"`{wrapped_specified_tgt.target.alias}` target.\n\n"
                "Hint: you should normally not specify this field so that Pants will find the "
                "`go_package` target for you."
            )
        return GoBinaryMainPackage(wrapped_specified_tgt.target.address)

    candidate_targets = await Get(Targets, AddressSpecs([SiblingAddresses(addr.spec_path)]))
    relevant_pkg_targets = [
        tgt
        for tgt in candidate_targets
        if tgt.has_field(GoPackageSourcesField) and tgt.residence_dir == addr.spec_path
    ]
    if len(relevant_pkg_targets) == 1:
        return GoBinaryMainPackage(relevant_pkg_targets[0].address)

    wrapped_tgt = await Get(WrappedTarget, Address, addr)
    alias = wrapped_tgt.target.alias
    if not relevant_pkg_targets:
        raise ResolveError(
            f"The `{alias}` target {addr} requires that there is a `go_package` "
            f"target defined in its directory {addr.spec_path}, but none were found.\n\n"
            "To fix, add a target like `go_package()` or `go_package(name='pkg')` to the BUILD "
            f"file in {addr.spec_path}."
        )
    raise ResolveError(
        f"There are multiple `go_package` targets for the same directory of the "
        f"`{alias}` target {addr}: {addr.spec_path}. It is ambiguous what to use as the `main` "
        "package.\n\n"
        f"To fix, please either set the `main` field for `{addr} or remove these "
        "`go_package` targets so that only one remains: "
        f"{sorted(tgt.address.spec for tgt in relevant_pkg_targets)}"
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
        *first_party_pkg.rules(),
        *import_analysis.rules(),
        UnionRule(InferDependenciesRequest, InferGoPackageDependenciesRequest),
        UnionRule(InjectDependenciesRequest, InjectGoThirdPartyPackageDependenciesRequest),
        UnionRule(InjectDependenciesRequest, InjectGoBinaryMainDependencyRequest),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromGoModRequest),
    )
