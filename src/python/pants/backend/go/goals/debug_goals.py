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
    GoThirdPartyDependenciesField,
    GoThirdPartyModuleDependenciesField,
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
from pants.backend.go.util_rules.build_pkg_third_party import (
    BuildGoPackageRequestForThirdPartyPackageRequest,
    setup_build_go_package_target_request_for_third_party,
)
from pants.backend.go.util_rules.cgo import CGoCompileRequest, CGoCompilerFlags, cgo_compile_request
from pants.backend.go.util_rules.first_party_pkg import (
    FirstPartyPkgAnalysisRequest,
    analyze_first_party_package,
)
from pants.backend.go.util_rules.go_mod import GoModInfoRequest, determine_go_mod_info
from pants.backend.go.util_rules.third_party_pkg import (
    AllThirdPartyPackagesRequest,
    ThirdPartyPkgAnalysisRequest,
    download_and_analyze_third_party_packages,
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
from pants.option.option_types import StrListOption
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class ShowGoPackageAnalysisSubsystem(GoalSubsystem):
    name = "go-show-package-analysis"
    help = "Show the package analysis for Go package targets."

    import_paths = StrListOption(
        help=softwrap(
            """
            Third-party packages to analyze by import path, resolved against the `go.mod` of the
            `go_third_party_module` target(s) passed on the command line.

            Under `[golang].third_party_target_granularity = "module"`, third-party packages other
            than a module's root do not have their own target, so pass the module target and select
            the package(s) to analyze with this option (mirroring `go_binary`'s `main_import_path`).
            Ignored for first-party and `go_third_party_package` targets.
            """
        ),
    )


class ShowGoPackageAnalysis(Goal):
    subsystem_cls = ShowGoPackageAnalysisSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY  # TODO(#17129) — Migrate this.


@goal_rule
async def go_show_package_analysis(
    targets: Targets, console: Console, analysis_subsystem: ShowGoPackageAnalysisSubsystem
) -> ShowGoPackageAnalysis:
    first_party_analysis_gets = []
    third_party_requests: list[ThirdPartyPkgAnalysisRequest] = []

    build_opts_by_target = await concurrently(
        go_extract_build_options_from_target(
            GoBuildOptionsFromTargetRequest(tgt.address), **implicitly()
        )
        for tgt in targets
    )

    requested_import_paths = analysis_subsystem.import_paths

    for target, build_opts in zip(targets, build_opts_by_target):
        if target.has_field(GoPackageSourcesField):
            first_party_analysis_gets.append(
                analyze_first_party_package(
                    FirstPartyPkgAnalysisRequest(target.address, build_opts=build_opts),
                    **implicitly(),
                )
            )
        elif target.has_field(GoThirdPartyDependenciesField):
            go_mod_address = target.address.maybe_convert_to_target_generator()
            go_mod_info = await determine_go_mod_info(GoModInfoRequest(go_mod_address))
            if requested_import_paths and target.has_field(GoThirdPartyModuleDependenciesField):
                import_paths = list(requested_import_paths)
            else:
                import_paths = [target[GoImportPathField].value]
            third_party_requests.extend(
                ThirdPartyPkgAnalysisRequest(
                    import_path,
                    go_mod_address,
                    go_mod_info.digest,
                    go_mod_info.mod_path,
                    build_opts=build_opts,
                )
                for import_path in import_paths
            )

    first_party_analysis_results = await concurrently(first_party_analysis_gets)

    for first_party_analysis_result in first_party_analysis_results:
        if first_party_analysis_result.analysis:
            console.write_stdout(str(first_party_analysis_result.analysis) + "\n")
        else:
            console.write_stdout(
                f"Error for {first_party_analysis_result.import_path}: {first_party_analysis_result.stderr}\n"
            )

    seen_requests: set[tuple[str, Address]] = set()
    for request in third_party_requests:
        request_key = (request.import_path, request.go_mod_address)
        if request_key in seen_requests:
            continue
        seen_requests.add(request_key)

        # Report an unknown import path instead of crashing; genuine analysis errors still propagate.
        all_packages = await download_and_analyze_third_party_packages(
            AllThirdPartyPackagesRequest(
                request.go_mod_address,
                request.go_mod_digest,
                request.go_mod_path,
                build_opts=request.build_opts,
            )
        )
        if request.import_path not in all_packages.import_paths_to_pkg_info:
            console.write_stdout(
                f"No Go package with import path `{request.import_path}` in `{request.go_mod_path}`.\n"
            )
            continue
        analysis = await extract_package_info(request, **implicitly())
        if analysis.error:
            console.write_stdout(f"Error for {analysis.import_path}: {analysis.error}\n")
        else:
            console.write_stdout(str(analysis) + "\n")

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

    import_paths = StrListOption(
        help=softwrap(
            """
            Third-party packages to export Cgo files for, by import path, resolved against the
            `go.mod` of the `go_third_party_module` target(s) passed on the command line.

            Under `[golang].third_party_target_granularity = "module"`, third-party packages other
            than a module's root do not have their own target, so pass the module target and select
            the package(s) with this option (mirroring `go_binary`'s `main_import_path`). Defaults
            to the module's root package. Ignored for first-party and `go_third_party_package`
            targets.
            """
        ),
    )


class GoExportCgoCodegen(Goal):
    subsystem_cls = GoExportCgoCodegenSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY  # TODO(#17129) — Migrate this.


@dataclass(frozen=True)
class ExportCgoPackageRequest:
    address: Address
    build_opts: GoBuildOptions
    # Module mode: package to build by import path within module target `address` (`None` builds `address`).
    import_path: str | None = None


@dataclass(frozen=True)
class ExportCgoPackageResult:
    digest: Digest = EMPTY_DIGEST
    error: str | None = None
    skip: bool = False


@rule
async def export_cgo_package(request: ExportCgoPackageRequest) -> ExportCgoPackageResult:
    # Analyze the package and ensure it is actually contains cgo code.
    if request.import_path is not None:
        fallible_build_req = await setup_build_go_package_target_request_for_third_party(
            BuildGoPackageRequestForThirdPartyPackageRequest(
                import_path=request.import_path,
                go_mod_address=request.address.maybe_convert_to_target_generator(),
                build_opts=request.build_opts,
            )
        )
    else:
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
    codegen_subsystem: GoExportCgoCodegenSubsystem,
) -> GoExportCgoCodegen:
    relevant_targets = [
        tgt
        for tgt in targets
        if tgt.has_field(GoPackageSourcesField) or tgt.has_field(GoThirdPartyDependenciesField)
    ]

    build_opts_by_target = await concurrently(
        go_extract_build_options_from_target(
            GoBuildOptionsFromTargetRequest(tgt.address), **implicitly()
        )
        for tgt in relevant_targets
    )

    requested_import_paths = codegen_subsystem.import_paths

    export_specs: list[tuple[str, ExportCgoPackageRequest]] = []
    for tgt, build_opts in zip(relevant_targets, build_opts_by_target):
        if not build_opts.cgo_enabled:
            logger.warning(f"Skipping target {tgt.address} because Cgo is not enabled for it.")
            continue
        if tgt.has_field(GoThirdPartyModuleDependenciesField):
            import_paths = (
                list(requested_import_paths)
                if requested_import_paths
                else [tgt[GoImportPathField].value]
            )
            for import_path in import_paths:
                # Prefix with the target address so same-path packages across go.mods don't collide.
                export_specs.append(
                    (
                        f"{tgt.address.path_safe_spec}/{import_path}",
                        ExportCgoPackageRequest(
                            tgt.address, build_opts=build_opts, import_path=import_path
                        ),
                    )
                )
        else:
            export_specs.append(
                (
                    tgt.address.path_safe_spec,
                    ExportCgoPackageRequest(tgt.address, build_opts=build_opts),
                )
            )

    cgo_results = await concurrently(export_cgo_package(request) for _, request in export_specs)

    for (export_label, _), cgo_result in zip(export_specs, cgo_results):
        if cgo_result.skip:
            continue
        if cgo_result.error:
            logger.error(f"{export_label}: {cgo_result.error}")
            continue

        export_dir = distdir_path.relpath / "cgo" / export_label
        workspace.write_digest(cgo_result.digest, path_prefix=str(export_dir))
        logger.info(f"{export_label}: Exported Cgo files to `{export_dir}`\n")

    return GoExportCgoCodegen(exit_code=0)


def rules():
    return (
        *collect_rules(),
        *first_party_pkg.rules(),
        *third_party_pkg.rules(),
    )
