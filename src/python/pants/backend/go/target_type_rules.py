# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

from pants.backend.go.dependency_inference import (
    AllGoModuleImportPathsMappings,
    GoImportPathsMappingAddressSet,
    GoModuleImportPathsMapping,
    GoModuleImportPathsMappings,
    GoModuleImportPathsMappingsHook,
    get_go_module_import_paths_mapping,
)
from pants.backend.go.target_types import (
    GoImportPathField,
    GoModSourcesField,
    GoModTarget,
    GoPackageSourcesField,
    GoThirdPartyPackageDependenciesField,
    GoThirdPartyPackageTarget,
)
from pants.backend.go.util_rules import build_opts, first_party_pkg, import_analysis
from pants.backend.go.util_rules.build_opts import (
    GoBuildOptions,
    GoBuildOptionsFromTargetRequest,
    go_extract_build_options_from_target,
)
from pants.backend.go.util_rules.first_party_pkg import (
    FirstPartyPkgAnalysisRequest,
    FirstPartyPkgImportPathRequest,
    analyze_first_party_package,
    compute_first_party_package_import_path,
)
from pants.backend.go.util_rules.go_mod import (
    GoModInfoRequest,
    OwningGoModRequest,
    determine_go_mod_info,
    find_owning_go_mod,
)
from pants.backend.go.util_rules.import_analysis import (
    GoStdLibPackagesRequest,
    analyze_go_stdlib_packages,
)
from pants.backend.go.util_rules.third_party_pkg import (
    AllThirdPartyPackagesRequest,
    ThirdPartyPkgAnalysis,
    ThirdPartyPkgAnalysisRequest,
    download_and_analyze_third_party_packages,
    extract_package_info,
)
from pants.core.target_types import (
    TargetGeneratorSourcesHelperSourcesField,
    TargetGeneratorSourcesHelperTarget,
)
from pants.engine.addresses import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.intrinsics import digest_to_snapshot
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import (
    AllTargets,
    Dependencies,
    FieldSet,
    GeneratedTargets,
    GenerateTargetsRequest,
    InferDependenciesRequest,
    InferredDependencies,
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

    owning_go_mod_targets = await concurrently(
        find_owning_go_mod(OwningGoModRequest(tgt.address), **implicitly())
        for tgt in candidate_go_source_targets
    )

    first_party_gets_metadata = []
    first_party_gets = []

    for tgt, owning_go_mod in zip(candidate_go_source_targets, owning_go_mod_targets):
        if tgt.has_field(GoImportPathField):
            import_path = tgt[GoImportPathField].value
            import_paths_by_module[owning_go_mod.address][import_path].add(tgt.address)
        elif tgt.has_field(GoPackageSourcesField):
            first_party_gets_metadata.append((tgt.address, owning_go_mod))
            first_party_gets.append(
                compute_first_party_package_import_path(FirstPartyPkgImportPathRequest(tgt.address))
            )

    first_party_import_paths = await concurrently(first_party_gets)
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
    all_results = await concurrently(
        get_go_module_import_paths_mapping(**implicitly({impl(): GoModuleImportPathsMappingsHook}))
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
    go_mod_addr = await find_owning_go_mod(
        OwningGoModRequest(request.field_set.address), **implicitly()
    )
    package_mapping, build_opts = await concurrently(
        map_import_paths_to_packages(
            GoImportPathMappingRequest(go_mod_addr.address), **implicitly()
        ),
        go_extract_build_options_from_target(
            GoBuildOptionsFromTargetRequest(go_mod_addr.address), **implicitly()
        ),
    )

    addr = request.field_set.address
    maybe_pkg_analysis, stdlib_packages = await concurrently(
        analyze_first_party_package(
            FirstPartyPkgAnalysisRequest(addr, build_opts=build_opts), **implicitly()
        ),
        analyze_go_stdlib_packages(
            GoStdLibPackagesRequest(with_race_detector=build_opts.with_race_detector)
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

    package_mapping, go_mod_info, build_opts = await concurrently(
        map_import_paths_to_packages(GoImportPathMappingRequest(go_mod_address), **implicitly()),
        determine_go_mod_info(GoModInfoRequest(go_mod_address)),
        go_extract_build_options_from_target(
            GoBuildOptionsFromTargetRequest(go_mod_address), **implicitly()
        ),
    )

    pkg_info, stdlib_packages = await concurrently(
        extract_package_info(
            ThirdPartyPkgAnalysisRequest(
                request.field_set.import_path.value,
                go_mod_address,
                go_mod_info.digest,
                go_mod_info.mod_path,
                build_opts=build_opts,
            )
        ),
        analyze_go_stdlib_packages(
            GoStdLibPackagesRequest(with_race_detector=build_opts.with_race_detector)
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


@rule(desc="Generate `go_third_party_package` targets from `go_mod` target", level=LogLevel.DEBUG)
async def generate_targets_from_go_mod(
    request: GenerateTargetsFromGoModRequest,
    union_membership: UnionMembership,
) -> GeneratedTargets:
    generator_addr = request.generator.address
    go_mod_sources = request.generator[GoModSourcesField]
    go_mod_info = await determine_go_mod_info(GoModInfoRequest(go_mod_sources))
    go_mod_snapshot = await digest_to_snapshot(go_mod_info.digest)
    all_packages = await download_and_analyze_third_party_packages(
        AllThirdPartyPackagesRequest(
            generator_addr,
            go_mod_info.digest,
            go_mod_info.mod_path,
            # TODO: There is a rule graph cycle in this rule if this rule tries to use GoBuildOptionsFromTargetRequest.
            # For now, just use a default set of options to facilitate analyzing third-party dependencies and
            # generating targets.
            build_opts=GoBuildOptions(),
        )
    )

    def gen_file_tgt(fp: str) -> TargetGeneratorSourcesHelperTarget:
        return TargetGeneratorSourcesHelperTarget(
            {TargetGeneratorSourcesHelperSourcesField.alias: fp},
            generator_addr.create_file(fp),
            union_membership,
        )

    file_tgts = [gen_file_tgt("go.mod")]
    if go_mod_sources.go_sum_path in go_mod_snapshot.files:
        file_tgts.append(gen_file_tgt("go.sum"))

    def create_tgt(pkg_info: ThirdPartyPkgAnalysis) -> GoThirdPartyPackageTarget:
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

    result = tuple(
        create_tgt(pkg_info) for pkg_info in all_packages.import_paths_to_pkg_info.values()
    ) + tuple(file_tgts)
    return GeneratedTargets(request.generator, result)


def rules():
    return (
        *collect_rules(),
        *build_opts.rules(),
        *first_party_pkg.rules(),
        *import_analysis.rules(),
        UnionRule(InferDependenciesRequest, InferGoPackageDependenciesRequest),
        UnionRule(InferDependenciesRequest, InferGoThirdPartyPackageDependenciesRequest),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromGoModRequest),
        UnionRule(GoModuleImportPathsMappingsHook, FirstPartyGoModuleImportPathsMappingsHook),
    )
