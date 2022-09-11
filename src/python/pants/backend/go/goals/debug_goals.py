# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.go.dependency_inference import GoModuleImportPathsMapping
from pants.backend.go.subsystems.golang import GolangSubsystem
from pants.backend.go.target_type_rules import GoImportPathMappingRequest
from pants.backend.go.target_types import (
    GoImportPathField,
    GoModTarget,
    GoPackageSourcesField,
    GoThirdPartyPackageDependenciesField,
)
from pants.backend.go.util_rules import first_party_pkg, third_party_pkg
from pants.backend.go.util_rules.cgo import CGoCompileRequest, CGoCompileResult
from pants.backend.go.util_rules.first_party_pkg import (
    FallibleFirstPartyPkgAnalysis,
    FallibleFirstPartyPkgDigest,
    FirstPartyPkgAnalysisRequest,
    FirstPartyPkgDigestRequest,
)
from pants.backend.go.util_rules.go_mod import GoModInfo, GoModInfoRequest
from pants.backend.go.util_rules.third_party_pkg import (
    ThirdPartyPkgAnalysis,
    ThirdPartyPkgAnalysisRequest,
)
from pants.core.util_rules.distdir import DistDir
from pants.engine.console import Console
from pants.engine.fs import Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.native_engine import Digest, RemovePrefix
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, goal_rule
from pants.engine.target import Targets, UnexpandedTargets


class ShowGoPackageAnalysisSubsystem(GoalSubsystem):
    name = "go-show-package-analysis"
    help = "Show the package analysis for Go package targets."


class ShowGoPackageAnalysis(Goal):
    subsystem_cls = ShowGoPackageAnalysisSubsystem


@goal_rule
async def go_show_package_analysis(targets: Targets, console: Console) -> ShowGoPackageAnalysis:
    first_party_analysis_gets = []
    third_party_analysis_gets = []

    for target in targets:
        if target.has_field(GoPackageSourcesField):
            first_party_analysis_gets.append(
                Get(FallibleFirstPartyPkgAnalysis, FirstPartyPkgAnalysisRequest(target.address))
            )
        elif target.has_field(GoThirdPartyPackageDependenciesField):
            import_path = target[GoImportPathField].value
            go_mod_address = target.address.maybe_convert_to_target_generator()
            go_mod_info = await Get(GoModInfo, GoModInfoRequest(go_mod_address))
            third_party_analysis_gets.append(
                Get(
                    ThirdPartyPkgAnalysis,
                    ThirdPartyPkgAnalysisRequest(
                        import_path, go_mod_info.digest, go_mod_info.mod_path
                    ),
                )
            )

    first_party_analysis_results = await MultiGet(first_party_analysis_gets)
    third_party_analysis_results = await MultiGet(third_party_analysis_gets)

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


@goal_rule
async def dump_go_import_paths_for_module(
    targets: UnexpandedTargets, console: Console
) -> DumpGoImportPathsForModule:
    for tgt in targets:
        console.write_stdout(
            f"Target: {tgt.address} ({tgt.__class__} ({isinstance(tgt, GoModTarget)})\n"
        )
        if not isinstance(tgt, GoModTarget):
            continue

        package_mapping = await Get(
            GoModuleImportPathsMapping, GoImportPathMappingRequest(tgt.address)
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


@goal_rule
async def go_export_cgo_codegen(
    targets: Targets,
    console: Console,
    distdir_path: DistDir,
    workspace: Workspace,
    golang_subsystem: GolangSubsystem,
) -> GoExportCgoCodegen:
    if not golang_subsystem.cgo_enabled:
        raise ValueError("Nothing to export since cgo is disabled.")

    go_package_targets = [tgt for tgt in targets if tgt.has_field(GoPackageSourcesField)]
    for tgt in go_package_targets:
        # Analyze the package and ensure it is actually contains cgo code.
        analysis_wrapper = await Get(
            FallibleFirstPartyPkgAnalysis, FirstPartyPkgAnalysisRequest(tgt.address)
        )
        if not analysis_wrapper.analysis:
            console.write_stdout(
                f"{tgt.address}: Failed to analyze target: {analysis_wrapper.stderr}\n"
            )
            continue
        analysis = analysis_wrapper.analysis
        if not analysis.cgo_files:
            console.write_stdout(
                f"{tgt.address}: Nothing to export because package does not contain Cgo files.\n"
            )
            continue
        fallible_digest_info = await Get(
            FallibleFirstPartyPkgDigest, FirstPartyPkgDigestRequest(tgt.address)
        )
        if not fallible_digest_info.pkg_digest:
            console.write_stdout(
                f"{tgt.address}: Failed to export due to failure to obtain package digest: {fallible_digest_info.stderr}\n"
            )
            continue

        # Perform CGo compilation.
        result = await Get(
            CGoCompileResult,
            CGoCompileRequest(
                import_path=analysis.import_path,
                pkg_name=analysis.name,
                digest=fallible_digest_info.pkg_digest.digest,
                dir_path=analysis.dir_path,
                cgo_files=analysis.cgo_files,
                cgo_flags=analysis.cgo_flags,
            ),
        )

        output_digest = await Get(Digest, RemovePrefix(result.digest, analysis.dir_path))

        export_dir = distdir_path.relpath / "__cgo__" / tgt.address.path_safe_spec
        workspace.write_digest(output_digest, path_prefix=str(export_dir))
        console.write_stdout(f"{tgt.address}: Exported to `{export_dir}`\n")

    return GoExportCgoCodegen(exit_code=0)


def rules():
    return (
        *collect_rules(),
        *first_party_pkg.rules(),
        *third_party_pkg.rules(),
    )
