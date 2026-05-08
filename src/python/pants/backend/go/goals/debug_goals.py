# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.go.target_type_rules import (
    GoImportPathMappingRequest,
    map_import_paths_to_packages,
)
from pants.backend.go.target_types import (
    GoImportPathField,
    GoModTarget,
    GoPackageSourcesField,
    GoThirdPartyPackageDependenciesField,
)
from pants.backend.go.util_rules import first_party_pkg, third_party_pkg
from pants.backend.go.util_rules.build_opts import (
    GoBuildOptions,
    GoBuildOptionsFromTargetRequest,
    go_extract_build_options_from_target,
)
from pants.backend.go.util_rules.build_pkg_target import (
    BuildGoPackageTargetRequest,
    setup_build_go_package_target_request,
)
from pants.backend.go.util_rules.cgo import CGoCompileRequest, CGoCompilerFlags, cgo_compile_request
from pants.backend.go.util_rules.first_party_pkg import (
    FirstPartyPkgAnalysisRequest,
    analyze_first_party_package,
)
from pants.backend.go.util_rules.go_mod import GoModInfoRequest, determine_go_mod_info
from pants.backend.go.util_rules.third_party_pkg import (
    ThirdPartyPkgAnalysisRequest,
    extract_package_info,
)
from pants.build_graph.address import Address
from pants.core.util_rules.distdir import DistDir
from pants.engine.console import Console
from pants.engine.fs import Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.native_engine import EMPTY_DIGEST, Digest, RemovePrefix
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import remove_prefix
from pants.engine.rules import collect_rules, goal_rule, implicitly, rule
from pants.engine.target import Targets, UnexpandedTargets

logger = logging.getLogger(__name__)


class ShowGoPackageAnalysisSubsystem(GoalSubsystem):
    name = "go-show-package-analysis"
    help = "Show the package analysis for Go package targets."


class ShowGoPackageAnalysis(Goal):
    subsystem_cls = ShowGoPackageAnalysisSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY  # TODO(#17129) — Migrate this.


@goal_rule
async def go_show_package_analysis(targets: Targets, console: Console) -> ShowGoPackageAnalysis:
    first_party_analysis_gets = []
    third_party_analysis_gets = []

    build_opts_by_target = await concurrently(
        go_extract_build_options_from_target(
            GoBuildOptionsFromTargetRequest(tgt.address), **implicitly()
        )
        for tgt in targets
    )

    for target, build_opts in zip(targets, build_opts_by_target):
        if target.has_field(GoPackageSourcesField):
            first_party_analysis_gets.append(
                analyze_first_party_package(
                    FirstPartyPkgAnalysisRequest(target.address, build_opts=build_opts),
                    **implicitly(),
                )
            )
        elif target.has_field(GoThirdPartyPackageDependenciesField):
            import_path = target[GoImportPathField].value
            go_mod_address = target.address.maybe_convert_to_target_generator()
            go_mod_info = await determine_go_mod_info(GoModInfoRequest(go_mod_address))
            third_party_analysis_gets.append(
                extract_package_info(
                    ThirdPartyPkgAnalysisRequest(
                        import_path,
                        go_mod_address,
                        go_mod_info.digest,
                        go_mod_info.mod_path,
                        build_opts=build_opts,
                    )
                )
            )

    first_party_analysis_results = await concurrently(first_party_analysis_gets)
    third_party_analysis_results = await concurrently(third_party_analysis_gets)

    for first_party_analysis_result in first_party_analysis_results:
        if first_party_analysis_result.analysis:
            console.write_stdout(str(first_party_analysis_result.analysis) + "\n")
        else:
            console.write_stdout(
                f"Error for {first_party_analysis_result.import_path}: {first_party_analysis_result.stderr}\n"
            )

    for third_party_analysis in third_party_analysis_results:
        if third_party_analysis.error:
            console.write_stdout(
                f"Error for {third_party_analysis.import_path}: {third_party_analysis.error}\n"
            )
        else:
            console.write_stdout(str(third_party_analysis) + "\n")

    return ShowGoPackageAnalysis(exit_code=0)


class DumpGoImportPathsForModuleSubsystem(GoalSubsystem):
    name = "go-dump-import-path-mapping"
    help = "Dump import paths mapped to package addresses."


class DumpGoImportPathsForModule(Goal):
    subsystem_cls = DumpGoImportPathsForModuleSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY  # TODO(#17129) — Migrate this.


@goal_rule
async def dump_go_import_paths_for_module(
    targets: UnexpandedTargets, console: Console
) -> DumpGoImportPathsForModule:
    for tgt in targets:
        if not isinstance(tgt, GoModTarget):
            continue

        console.write_stdout(f"{tgt.address}:\n")
        package_mapping = await map_import_paths_to_packages(
            GoImportPathMappingRequest(tgt.address), **implicitly()
        )
        for import_path, address_set in package_mapping.mapping.items():
            maybe_infer_all = " (infer all)" if address_set.infer_all else ""
            console.write_stdout(
                f"  {import_path}: {', '.join(sorted([str(addr) for addr in address_set.addresses]))}{maybe_infer_all}\n"
            )

    return DumpGoImportPathsForModule(exit_code=0)


class GoExportCgoCodegenSubsystem(GoalSubsystem):
    name = "go-export-cgo-codegen"
    help = "Export files generated by Cgo."


class GoExportCgoCodegen(Goal):
    subsystem_cls = GoExportCgoCodegenSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY  # TODO(#17129) — Migrate this.


@dataclass(frozen=True)
class ExportCgoPackageRequest:
    address: Address
    build_opts: GoBuildOptions


@dataclass(frozen=True)
class ExportCgoPackageResult:
    digest: Digest = EMPTY_DIGEST
    error: str | None = None
    skip: bool = False


@rule
async def export_cgo_package(request: ExportCgoPackageRequest) -> ExportCgoPackageResult:
    # Analyze the package and ensure it is actually contains cgo code.
    fallible_build_req = await setup_build_go_package_target_request(
        BuildGoPackageTargetRequest(
            address=request.address,
            build_opts=request.build_opts,
        ),
        **implicitly(),
    )

    build_req = fallible_build_req.request
    if not build_req:
        return ExportCgoPackageResult(
            error=f"Failed to analyze target: {fallible_build_req.stderr}"
        )

    if not build_req.build_opts.cgo_enabled:
        logger.warning(f"Skipping target {request.address} because Cgo is not enabled for it.")
        return ExportCgoPackageResult(skip=True)

    if not build_req.cgo_files:
        return ExportCgoPackageResult(skip=True)

    # Perform CGo compilation.
    result = await cgo_compile_request(
        CGoCompileRequest(
            import_path=build_req.import_path,
            pkg_name=build_req.pkg_name,
            digest=build_req.digest,
            build_opts=build_req.build_opts,
            dir_path=build_req.dir_path,
            cgo_files=build_req.cgo_files,
            cgo_flags=build_req.cgo_flags or CGoCompilerFlags.empty(),
        ),
        **implicitly(),
    )

    output_digest = await remove_prefix(RemovePrefix(result.digest, build_req.dir_path))
    return ExportCgoPackageResult(digest=output_digest)


@goal_rule
async def go_export_cgo_codegen(
    targets: Targets,
    distdir_path: DistDir,
    workspace: Workspace,
) -> GoExportCgoCodegen:
    package_targets = [
        tgt
        for tgt in targets
        if tgt.has_field(GoPackageSourcesField)
        or tgt.has_field(GoThirdPartyPackageDependenciesField)
    ]

    build_opts_by_target = await concurrently(
        go_extract_build_options_from_target(
            GoBuildOptionsFromTargetRequest(tgt.address), **implicitly()
        )
        for tgt in package_targets
    )

    targets_to_process = []
    for tgt, build_opts in zip(package_targets, build_opts_by_target):
        if not build_opts.cgo_enabled:
            logger.warning(f"Skipping target {tgt.address} because Cgo is not enabled for it.")
            continue
        targets_to_process.append((tgt, build_opts))

    cgo_results = await concurrently(
        export_cgo_package(ExportCgoPackageRequest(tgt.address, build_opts=build_opts))
        for tgt, build_opts in targets_to_process
    )

    for (tgt, build_opts), cgo_result in zip(targets_to_process, cgo_results):
        if cgo_result.skip:
            continue
        if cgo_result.error:
            logger.error(f"{tgt.address}: {cgo_result.error}")
            continue

        export_dir = distdir_path.relpath / "cgo" / tgt.address.path_safe_spec
        workspace.write_digest(cgo_result.digest, path_prefix=str(export_dir))
        logger.info(f"{tgt.address}: Exported Cgo files to `{export_dir}`\n")

    return GoExportCgoCodegen(exit_code=0)


def rules():
    return (
        *collect_rules(),
        *first_party_pkg.rules(),
        *third_party_pkg.rules(),
    )
