# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

from pants.backend.go.dependency_inference import (
    AllGoModuleImportPathsMappings,
    GoImportPathsMappingAddressSet,
    GoModuleImportPathsMapping,
    GoModuleImportPathsMappings,
    GoModuleImportPathsMappingsHook,
)
from pants.backend.go.target_types import (
    GoImportPathField,
    GoModSourcesField,
    GoModTarget,
    GoPackageSourcesField,
    GoThirdPartyPackageDependenciesField,
    GoThirdPartyPackageTarget,
    GoVendoredModuleDirPath,
    GoVendoredModuleImportPathField,
    GoVendoredPackageDigestField,
    GoVendoredPackageDirPath,
    GoVendoredPackageTarget,
)
from pants.backend.go.util_rules import build_opts, first_party_pkg, import_analysis, vendor
from pants.backend.go.util_rules.build_opts import GoBuildOptions, GoBuildOptionsFromTargetRequest
from pants.backend.go.util_rules.first_party_pkg import (
    FallibleFirstPartyPkgAnalysis,
    FirstPartyPkgAnalysisRequest,
    FirstPartyPkgImportPath,
    FirstPartyPkgImportPathRequest,
)
from pants.backend.go.util_rules.go_mod import (
    GoModInfo,
    GoModInfoRequest,
    OwningGoMod,
    OwningGoModRequest,
)
from pants.backend.go.util_rules.import_analysis import GoStdLibPackages, GoStdLibPackagesRequest
from pants.backend.go.util_rules.third_party_pkg import (
    AllThirdPartyPackages,
    AllThirdPartyPackagesRequest,
    ThirdPartyPkgAnalysis,
    ThirdPartyPkgAnalysisRequest,
)
from pants.backend.go.util_rules.vendor import (
    ParseVendorModulesMetadataRequest,
    ParseVendorModulesMetadataResult,
    VendoredModuleMetadata,
)
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.core.target_types import (
    TargetGeneratorSourcesHelperSourcesField,
    TargetGeneratorSourcesHelperTarget,
)
from pants.engine.addresses import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import Digest, PathGlobs, Snapshot
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    AllTargets,
    Dependencies,
    FieldSet,
    GeneratedTargets,
    GenerateTargetsRequest,
    InferDependenciesRequest,
    InferredDependencies,
    Target,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GoImportPathMappingRequest(EngineAwareParameter):
    go_mod_address: Address

    def debug_hint(self) -> str | None:
        return str(self.go_mod_address)


class FirstPartyGoModuleImportPathsMappingsHook(GoModuleImportPathsMappingsHook):
    pass


@rule(desc="Analyze and map Go import paths for all modules.", level=LogLevel.DEBUG)
async def go_map_import_paths_by_module(
    _request: FirstPartyGoModuleImportPathsMappingsHook,
    all_targets: AllTargets,
) -> GoModuleImportPathsMappings:
    import_paths_by_module: dict[Address, dict[str, set[Address]]] = defaultdict(
        lambda: defaultdict(set)
    )

    candidate_go_source_targets = [
        tgt
        for tgt in all_targets
        if (tgt.has_field(GoImportPathField) or tgt.has_field(GoPackageSourcesField))
    ]

    owning_go_mod_targets = await MultiGet(
        Get(OwningGoMod, OwningGoModRequest(tgt.address)) for tgt in candidate_go_source_targets
    )

    first_party_gets_metadata = []
    first_party_gets = []

    for tgt, owning_go_mod in zip(candidate_go_source_targets, owning_go_mod_targets):
        if tgt.has_field(GoImportPathField) and tgt[GoImportPathField].value is not None:
            import_path = tgt[GoImportPathField].value
            import_paths_by_module[owning_go_mod.address][import_path].add(tgt.address)
        elif tgt.has_field(GoPackageSourcesField):
            first_party_gets_metadata.append((tgt.address, owning_go_mod))
            first_party_gets.append(
                Get(FirstPartyPkgImportPath, FirstPartyPkgImportPathRequest(tgt.address))
            )

    first_party_import_paths = await MultiGet(first_party_gets)
    for import_path_info, (addr, owning_go_mod) in zip(
        first_party_import_paths, first_party_gets_metadata
    ):
        import_paths_by_module[owning_go_mod.address][import_path_info.import_path].add(addr)

    return GoModuleImportPathsMappings(
        FrozenDict(
            {
                go_mod_addr: GoModuleImportPathsMapping(
                    mapping=FrozenDict(
                        {
                            import_path: GoImportPathsMappingAddressSet(
                                addresses=tuple(sorted(addresses)), infer_all=False
                            )
                            for import_path, addresses in import_path_mapping.items()
                        }
                    ),
                    address_to_import_path=FrozenDict(
                        {
                            address: import_path
                            for import_path, addresses in import_path_mapping.items()
                            for address in addresses
                        }
                    ),
                )
                for go_mod_addr, import_path_mapping in import_paths_by_module.items()
            }
        )
    )


@rule(desc="Analyze Go import paths for all modules.", level=LogLevel.DEBUG)
async def go_merge_import_paths_analysis(
    union_membership: UnionMembership,
) -> AllGoModuleImportPathsMappings:
    import_path_mappers = union_membership.get(GoModuleImportPathsMappingsHook)
    all_results = await MultiGet(
        Get(GoModuleImportPathsMappings, GoModuleImportPathsMappingsHook, impl())
        for impl in import_path_mappers
    )

    import_paths_by_module: dict[Address, dict[str, set[Address]]] = defaultdict(
        lambda: defaultdict(set)
    )
    infer_all_by_module: dict[Address, dict[str, bool]] = defaultdict(lambda: defaultdict(bool))

    # Merge all of the mappings together.
    for result in all_results:
        for go_mod_address, mapping in result.modules.items():
            imports_paths_for_module = import_paths_by_module[go_mod_address]
            for import_path, address_set in mapping.mapping.items():
                for address in address_set.addresses:
                    imports_paths_for_module[import_path].add(address)
                if address_set.infer_all:
                    infer_all_by_module[go_mod_address][import_path] = True

    return AllGoModuleImportPathsMappings(
        FrozenDict(
            {
                go_mod_addr: GoModuleImportPathsMapping(
                    mapping=FrozenDict(
                        {
                            import_path: GoImportPathsMappingAddressSet(
                                addresses=tuple(sorted(addresses)),
                                infer_all=infer_all_by_module[go_mod_addr][import_path],
                            )
                            for import_path, addresses in import_path_mapping.items()
                        }
                    ),
                    address_to_import_path=FrozenDict(
                        {
                            address: import_path
                            for import_path, addresses in import_path_mapping.items()
                            for address in addresses
                        }
                    ),
                )
                for go_mod_addr, import_path_mapping in import_paths_by_module.items()
            }
        )
    )


@rule(desc="Map Go targets owned by module to import paths", level=LogLevel.DEBUG)
async def map_import_paths_to_packages(
    request: GoImportPathMappingRequest,
    module_import_path_mappings: AllGoModuleImportPathsMappings,
) -> GoModuleImportPathsMapping:
    return module_import_path_mappings.modules[request.go_mod_address]


@dataclass(frozen=True)
class GoPackageDependenciesInferenceFieldSet(FieldSet):
    required_fields = (GoPackageSourcesField,)

    sources: GoPackageSourcesField


class InferGoPackageDependenciesRequest(InferDependenciesRequest):
    infer_from = GoPackageDependenciesInferenceFieldSet


@rule(desc="Infer dependencies for first-party Go packages", level=LogLevel.DEBUG)
async def infer_go_dependencies(
    request: InferGoPackageDependenciesRequest,
) -> InferredDependencies:
    go_mod_addr = await Get(OwningGoMod, OwningGoModRequest(request.field_set.address))
    package_mapping, build_opts = await MultiGet(
        Get(GoModuleImportPathsMapping, GoImportPathMappingRequest(go_mod_addr.address)),
        Get(GoBuildOptions, GoBuildOptionsFromTargetRequest(go_mod_addr.address)),
    )

    addr = request.field_set.address
    maybe_pkg_analysis, stdlib_packages = await MultiGet(
        Get(
            FallibleFirstPartyPkgAnalysis, FirstPartyPkgAnalysisRequest(addr, build_opts=build_opts)
        ),
        Get(
            GoStdLibPackages,
            GoStdLibPackagesRequest(with_race_detector=build_opts.with_race_detector),
        ),
    )

    if maybe_pkg_analysis.analysis is None:
        logger.error(
            f"Failed to analyze {maybe_pkg_analysis.import_path} for dependency inference:\n"
            f"{maybe_pkg_analysis.stderr}"
        )
        return InferredDependencies([])
    pkg_analysis = maybe_pkg_analysis.analysis

    inferred_dependencies: list[Address] = []
    for import_path in (
        *pkg_analysis.imports,
        *pkg_analysis.test_imports,
        *pkg_analysis.xtest_imports,
    ):
        # Avoid a dependency cycle caused by external test imports of this package (i.e., "xtest").
        if import_path == pkg_analysis.import_path:
            continue
        candidate_packages = package_mapping.mapping.get(import_path)
        if candidate_packages:
            if candidate_packages.infer_all:
                inferred_dependencies.extend(candidate_packages.addresses)
            else:
                if len(candidate_packages.addresses) > 1:
                    # TODO(#12761): Use ExplicitlyProvidedDependencies for disambiguation.
                    logger.warning(
                        f"Ambiguous mapping for import path {import_path} on packages at addresses: {candidate_packages}"
                    )
                elif len(candidate_packages.addresses) == 1:
                    inferred_dependencies.append(candidate_packages.addresses[0])
                else:
                    logger.debug(
                        f"Unable to infer dependency for import path '{import_path}' "
                        f"in go_package at address '{addr}'."
                    )
        else:
            logger.debug(
                f"Unable to infer dependency for import path '{import_path}' "
                f"in go_package at address '{addr}'."
            )

    return InferredDependencies(inferred_dependencies)


@dataclass(frozen=True)
class GoThirdPartyPackageInferenceFieldSet(FieldSet):
    required_fields = (GoThirdPartyPackageDependenciesField, GoImportPathField)

    dependencies: GoThirdPartyPackageDependenciesField
    import_path: GoImportPathField


class InferGoThirdPartyPackageDependenciesRequest(InferDependenciesRequest):
    infer_from = GoThirdPartyPackageInferenceFieldSet


@rule(desc="Infer dependencies for third-party Go packages", level=LogLevel.DEBUG)
async def infer_go_third_party_package_dependencies(
    request: InferGoThirdPartyPackageDependenciesRequest,
) -> InferredDependencies:
    addr = request.field_set.address
    go_mod_address = addr.maybe_convert_to_target_generator()

    package_mapping, go_mod_info, build_opts = await MultiGet(
        Get(GoModuleImportPathsMapping, GoImportPathMappingRequest(go_mod_address)),
        Get(GoModInfo, GoModInfoRequest(go_mod_address)),
        Get(GoBuildOptions, GoBuildOptionsFromTargetRequest(go_mod_address)),
    )

    pkg_info, stdlib_packages = await MultiGet(
        Get(
            ThirdPartyPkgAnalysis,
            ThirdPartyPkgAnalysisRequest(
                request.field_set.import_path.value,
                go_mod_address,
                go_mod_info.digest,
                go_mod_info.mod_path,
                build_opts=build_opts,
            ),
        ),
        Get(
            GoStdLibPackages,
            GoStdLibPackagesRequest(with_race_detector=build_opts.with_race_detector),
        ),
    )

    inferred_dependencies: list[Address] = []
    for import_path in pkg_info.imports:
        candidate_packages = package_mapping.mapping.get(import_path, ())
        if candidate_packages:
            if candidate_packages.infer_all:
                inferred_dependencies.extend(candidate_packages.addresses)
            else:
                if len(candidate_packages.addresses) > 1:
                    # TODO(#12761): Use ExplicitlyProvidedDependencies for disambiguation.
                    logger.warning(
                        f"Ambiguous mapping for import path {import_path} on packages at addresses: {candidate_packages}"
                    )
                elif len(candidate_packages.addresses) == 1:
                    inferred_dependencies.append(candidate_packages.addresses[0])
                else:
                    logger.debug(
                        f"Unable to infer dependency for import path '{import_path}' "
                        f"in go_third_party_package at address '{addr}'."
                    )
        else:
            logger.debug(
                f"Unable to infer dependency for import path '{import_path}' "
                f"in go_third_party_package at address '{addr}'."
            )

    return InferredDependencies(inferred_dependencies)


# -----------------------------------------------------------------------------------------------
# Generate `go_third_party_package` targets
# -----------------------------------------------------------------------------------------------


class GenerateTargetsFromGoModRequest(GenerateTargetsRequest):
    generate_from = GoModTarget


@dataclass(frozen=True)
class _GenerateVendoredModuleTargetRequest(EngineAwareParameter):
    vendor_path: PurePath
    module: VendoredModuleMetadata
    generator_addr: Address
    template: dict[str, Any] = dataclasses.field(hash=False)

    def debug_hint(self) -> str | None:
        return f"{self.vendor_path}: {self.module.module_import_path}"


@dataclass(frozen=True)
class _GenerateVendoredModuleTargetsResult:
    targets: tuple[Target, ...]


@rule(desc="Generate `_go_vendored_package` target for vendored package", level=LogLevel.DEBUG)
async def generate_go_vendored_package_target(
    request: _GenerateVendoredModuleTargetRequest,
    union_membership: UnionMembership,
) -> _GenerateVendoredModuleTargetsResult:
    # Capture the digest for the module. This digest includes all of the sources of the module and is made available
    # to all packages within the vendored module.
    module_dir_path = request.vendor_path.joinpath(request.module.module_import_path)
    module_digest = await Get(
        Digest,
        PathGlobs(
            [str(module_dir_path)],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin=f"the vendored module `{request.module.module_import_path}` under `{request.vendor_path}`",
        ),
    )
    module_digest_str = f"{module_digest.fingerprint}/{module_digest.serialized_bytes_length}"

    def generate_target(pkg_import_path: str) -> GoVendoredPackageTarget:
        return GoVendoredPackageTarget(
            {
                **request.template,
                GoImportPathField.alias: pkg_import_path,
                GoVendoredModuleImportPathField.alias: request.module.module_import_path,
                GoVendoredPackageDigestField.alias: module_digest_str,  # TODO: Can this be `Digest` directly?
                GoVendoredModuleDirPath.alias: str(module_dir_path),
                GoVendoredPackageDirPath.alias: str(request.vendor_path.joinpath(pkg_import_path)),
            },
            # E.g. `src/go:mod#github.com/google/uuid`.
            request.generator_addr.create_generated(pkg_import_path),
            union_membership,
            residence_dir=request.generator_addr.spec_path,
        )

    targets = tuple(
        generate_target(pkg_import_path) for pkg_import_path in request.module.package_import_paths
    )
    return _GenerateVendoredModuleTargetsResult(targets)


@rule(desc="Generate `go_third_party_package` targets from `go_mod` target", level=LogLevel.DEBUG)
async def generate_targets_from_go_mod(
    request: GenerateTargetsFromGoModRequest,
    union_membership: UnionMembership,
) -> GeneratedTargets:
    generator_addr = request.generator.address
    go_mod_sources = request.generator[GoModSourcesField]
    go_mod_info = await Get(GoModInfo, GoModInfoRequest(go_mod_sources))
    go_mod_snapshot = await Get(Snapshot, Digest, go_mod_info.digest)
    vendor_module_config_path = PurePath(go_mod_info.mod_path, "vendor", "modules.txt")
    all_packages, vendor_module_config_snapshot = await MultiGet(
        Get(
            AllThirdPartyPackages,
            AllThirdPartyPackagesRequest(
                generator_addr,
                go_mod_info.digest,
                go_mod_info.mod_path,
                # TODO: There is a rule graph cycle in this rule if this rule tries to use GoBuildOptionsFromTargetRequest.
                # For now, just use a default set of options to facilitate analyzing third-party dependencies and
                # generating targets.
                build_opts=GoBuildOptions(),
            ),
        ),
        Get(Snapshot, PathGlobs([str(vendor_module_config_path)])),
    )

    vendor_module_targets: tuple[Target, ...] = ()
    if vendor_module_config_snapshot.files:
        vendor_module_config = await Get(
            ParseVendorModulesMetadataResult,
            ParseVendorModulesMetadataRequest(
                digest=vendor_module_config_snapshot.digest,
                path=str(vendor_module_config_path),
            ),
        )
        vendor_modules = await MultiGet(
            Get(
                _GenerateVendoredModuleTargetsResult,
                _GenerateVendoredModuleTargetRequest(
                    vendor_path=vendor_module_config_path.parent,
                    module=module_config,
                    generator_addr=request.generator.address,
                    template=request.template,
                ),
            )
            for module_config in vendor_module_config.modules
        )
        tgts: list[Target] = []
        for m in vendor_modules:
            tgts.extend(m.targets)
        vendor_module_targets = tuple(tgts)

    def gen_file_tgt(fp: str) -> TargetGeneratorSourcesHelperTarget:
        return TargetGeneratorSourcesHelperTarget(
            {TargetGeneratorSourcesHelperSourcesField.alias: fp},
            generator_addr.create_file(fp),
            union_membership,
        )

    file_tgts = [gen_file_tgt("go.mod")]
    if go_mod_sources.go_sum_path in go_mod_snapshot.files:
        file_tgts.append(gen_file_tgt("go.sum"))

    def create_third_party_target(pkg_info: ThirdPartyPkgAnalysis) -> GoThirdPartyPackageTarget:
        return GoThirdPartyPackageTarget(
            {
                **request.template,
                GoImportPathField.alias: pkg_info.import_path,
                Dependencies.alias: [t.address.spec for t in file_tgts],
            },
            # E.g. `src/go:mod#github.com/google/uuid`.
            generator_addr.create_generated(pkg_info.import_path),
            union_membership,
            residence_dir=generator_addr.spec_path,
        )

    third_party_targets = tuple(
        create_third_party_target(pkg_info)
        for pkg_info in all_packages.import_paths_to_pkg_info.values()
    )

    result = third_party_targets + tuple(file_tgts) + vendor_module_targets
    return GeneratedTargets(request.generator, result)


def rules():
    return (
        *collect_rules(),
        *build_opts.rules(),
        *first_party_pkg.rules(),
        *import_analysis.rules(),
        *vendor.rules(),
        UnionRule(InferDependenciesRequest, InferGoPackageDependenciesRequest),
        UnionRule(InferDependenciesRequest, InferGoThirdPartyPackageDependenciesRequest),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromGoModRequest),
        UnionRule(GoModuleImportPathsMappingsHook, FirstPartyGoModuleImportPathsMappingsHook),
    )
