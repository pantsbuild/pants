# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from pants.backend.javascript.nodejs_project import AllNodeJSProjects
from pants.backend.javascript.package_json import (
    AllPackageJson,
    OwningNodePackageRequest,
    find_owning_package,
)
from pants.backend.javascript.resolve import ChosenNodeResolve, RequestNodeResolve
from pants.backend.javascript.subsystems.nodejs_tool import NodeJSToolRequest
from pants.backend.typescript.subsystem import TypeScriptSubsystem
from pants.backend.typescript.target_types import TypeScriptSourceField, TypeScriptTestSourceField
from pants.backend.typescript.tsconfig import AllTSConfigs
from pants.build_graph.address import Address
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.core.target_types import FileSourceField
from pants.engine.fs import EMPTY_DIGEST, Digest, DigestSubset, GlobMatchErrorBehavior, PathGlobs
from pants.engine.internals.graph import hydrate_sources
from pants.engine.internals.native_engine import MergeDigests
from pants.engine.internals.selectors import Get, concurrently
from pants.engine.intrinsics import execute_process, merge_digests, path_globs_to_digest
from pants.engine.process import Process
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import (
    AllTargets,
    FieldSet,
    HydrateSourcesRequest,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobalOptions
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pants.backend.javascript.nodejs_project import NodeJSProject


async def _load_cached_typescript_artifacts(project: NodeJSProject) -> Digest:
    """Load cached .tsbuildinfo files and output files for incremental TypeScript compilation."""
    cache_globs = []
    for workspace_pkg in project.workspaces:
        # Cache .tsbuildinfo files for incremental state
        cache_globs.append(f"{workspace_pkg.root_dir}/tsconfig.tsbuildinfo")
        # Cache output directories that TypeScript --build generates
        # TODO: How to handle different output directories?
        cache_globs.append(f"{workspace_pkg.root_dir}/dist/**/*")

    cached_artifacts = await path_globs_to_digest(
        PathGlobs(cache_globs, glob_match_error_behavior=GlobMatchErrorBehavior.ignore),
        **implicitly(),
    )

    return cached_artifacts


async def _extract_typescript_artifacts_for_caching(
    project: NodeJSProject, process_output_digest: Digest
) -> Digest:
    """Extract .tsbuildinfo files and output files from TypeScript compilation for caching."""
    output_globs = []
    for workspace_pkg in project.workspaces:
        # Extract .tsbuildinfo files for incremental state
        output_globs.append(f"{workspace_pkg.root_dir}/tsconfig.tsbuildinfo")
        # Extract output directories that TypeScript --build generates
        # PR_NOTE: Currently hardcoded to 'dist' but TypeScript projects may use different
        # output directories (e.g., 'build', 'lib', 'out'). This could be improved by
        # parsing tsconfig.json's outDir/declarationDir settings.
        output_globs.append(f"{workspace_pkg.root_dir}/dist/**/*")

    artifacts_digest = await Get(
        Digest,
        DigestSubset(
            process_output_digest,
            PathGlobs(output_globs, glob_match_error_behavior=GlobMatchErrorBehavior.ignore),
        ),
    )

    return artifacts_digest


async def _collect_config_files_for_project(
    project: NodeJSProject,
    all_package_json: AllPackageJson,
    all_ts_configs: AllTSConfigs,
) -> list[str]:
    """Collect all configuration files needed for TypeScript compilation in a project.

    This includes:
    - package.json files (for dependencies and module resolution)
    - tsconfig.json files (for TypeScript compiler configuration)
    - Package manager config files (.npmrc, .pnpmrc, pnpm-workspace.yaml)

    PR_NOTE: We need to look for config files declared as explicit file targets because:
    1. Package manager config files (.npmrc, .pnpmrc) affect how dependencies are resolved
    2. Workspace config files (pnpm-workspace.yaml) define monorepo structure
    3. These files might not be auto-discovered by AllPackageJson/AllTSConfigs if they
       don't follow standard naming or if users explicitly manage them as file targets
    """
    config_files = []

    # Add discovered package.json files
    project_package_jsons = [
        pkg for pkg in all_package_json if pkg.root_dir.startswith(project.root_dir)
    ]
    for pkg_json in project_package_jsons:
        config_files.append(pkg_json.file)

    # Add discovered tsconfig.json files
    project_ts_configs = [
        config for config in all_ts_configs if config.path.startswith(project.root_dir)
    ]
    for ts_config in project_ts_configs:
        config_files.append(ts_config.path)

    # Find package manager config files declared as explicit file targets
    # This is necessary for files like .npmrc that affect dependency resolution
    project_root_address = Address(project.root_dir)
    transitive_targets = await Get(
        TransitiveTargets, TransitiveTargetsRequest([project_root_address])
    )

    for target in transitive_targets.closure:
        if target.has_field(FileSourceField):
            file_path = target[FileSourceField].file_path
            file_name = file_path.split("/")[-1]
            # Check for package manager config files
            if file_name in (".npmrc", ".pnpmrc", "pnpm-workspace.yaml") and file_path.startswith(
                project.root_dir
            ):
                config_files.append(file_path)

    return config_files


@dataclass(frozen=True)
class TypeScriptCheckFieldSet(FieldSet):
    required_fields = (TypeScriptSourceField,)

    sources: TypeScriptSourceField


@dataclass(frozen=True)
class TypeScriptTestCheckFieldSet(FieldSet):
    required_fields = (TypeScriptTestSourceField,)

    sources: TypeScriptTestSourceField


class TypeScriptCheckRequest(CheckRequest):
    field_set_type = TypeScriptCheckFieldSet
    tool_name = TypeScriptSubsystem.options_scope


class TypeScriptTestCheckRequest(CheckRequest):
    field_set_type = TypeScriptTestCheckFieldSet
    tool_name = TypeScriptSubsystem.options_scope


async def _typecheck_single_project(
    project: NodeJSProject,
    subsystem: TypeScriptSubsystem,
    global_options: GlobalOptions,
) -> CheckResult:
    """Type check a single TypeScript project."""
    all_targets = await Get(AllTargets)

    # Find all TypeScript targets
    typescript_targets = [
        target
        for target in all_targets
        if (target.has_field(TypeScriptSourceField) or target.has_field(TypeScriptTestSourceField))
    ]

    # Get owning packages for all TypeScript targets concurrently
    typescript_owning_packages = await concurrently(
        find_owning_package(OwningNodePackageRequest(target.address), **implicitly())
        for target in typescript_targets
    )

    # Filter to targets that belong to the current project
    all_projects = await Get(AllNodeJSProjects)
    project_typescript_targets = []
    for i, owning_package in enumerate(typescript_owning_packages):
        target = typescript_targets[i]
        if owning_package.target:
            package_directory = owning_package.target.address.spec_path
            target_project = all_projects.project_for_directory(package_directory)
            if target_project == project:
                project_typescript_targets.append(target)

    # Get source files from all TypeScript targets in the project
    if project_typescript_targets:
        workspace_target_sources = await concurrently(
            hydrate_sources(
                HydrateSourcesRequest(
                    target[TypeScriptSourceField]
                    if target.has_field(TypeScriptSourceField)
                    else target[TypeScriptTestSourceField]
                ),
                **implicitly(),
            )
            for target in project_typescript_targets
        )

        # Merge all workspace target sources
        all_workspace_digests = [sources.snapshot.digest for sources in workspace_target_sources]
        all_workspace_sources = await merge_digests(MergeDigests(all_workspace_digests))

    else:
        logger.warning(f"No TypeScript targets found in project {project.root_dir}")
        return CheckResult(
            exit_code=0,
            stdout="",
            stderr="",
            partition_description=f"TypeScript check on {project.root_dir} (no targets)",
        )

    # Collect all config files needed for TypeScript compilation
    all_package_json, all_ts_configs = await concurrently(
        Get(AllPackageJson),
        Get(AllTSConfigs),
    )

    config_files = await _collect_config_files_for_project(
        project, all_package_json, all_ts_configs
    )

    # Get config file digests
    config_digests = []
    for config_file in config_files:
        config_digest = await path_globs_to_digest(
            PathGlobs([config_file], glob_match_error_behavior=GlobMatchErrorBehavior.ignore),
            **implicitly(),
        )
        config_digests.append(config_digest)

    # Include cached .tsbuildinfo files and output files for incremental compilation
    # TypeScript --build uses these files to skip unchanged packages
    cached_typescript_artifacts = await _load_cached_typescript_artifacts(project)

    # Merge workspace sources, config files, and cached TypeScript artifacts
    all_digests = (
        [all_workspace_sources]
        + config_digests
        + ([cached_typescript_artifacts] if cached_typescript_artifacts != EMPTY_DIGEST else [])
    )
    input_digest = await merge_digests(MergeDigests(all_digests))

    # Use --build to compile all projects in workspace with project references
    args = ("--build",)

    # Determine which resolve to use for this TypeScript project
    # Use the project's root directory to get the correct resolve
    # - For monorepos: all workspaces share the parent project's lockfile/resolve
    # - For standalone projects: the project root contains the lockfile/resolve
    project_address = Address(project.root_dir)
    project_resolve = await Get(ChosenNodeResolve, RequestNodeResolve(project_address))

    # Use the TypeScript subsystem's tool request with the discovered resolve
    tool_request = subsystem.request(
        args=args,
        input_digest=input_digest,
        description=f"Type-check TypeScript project {project.root_dir} ({len(project_typescript_targets)} targets)",
        level=LogLevel.DEBUG,
    )

    # Override the resolve to use the project's resolve instead of default
    tool_request_with_resolve = replace(tool_request, resolve=project_resolve.resolve_name)

    # Execute TypeScript type checking with the project's resolve
    process = await Get(Process, NodeJSToolRequest, tool_request_with_resolve)

    # Set working directory to the project root where tsconfig.json is located
    working_directory = project.root_dir if project.root_dir != "." else None
    process_with_workdir = (
        replace(process, working_directory=working_directory) if working_directory else process
    )

    result = await execute_process(process_with_workdir, **implicitly())

    # Cache TypeScript incremental build artifacts for faster subsequent runs
    # TypeScript --build generates .tsbuildinfo files and output files that enable incremental compilation
    typescript_artifacts_digest = await _extract_typescript_artifacts_for_caching(
        project, result.output_digest
    )

    # Convert to CheckResult with caching support - single result for the project
    check_result = CheckResult.from_fallible_process_result(
        result,
        partition_description=f"TypeScript check on {project.root_dir} ({len(project_typescript_targets)} targets)",
        # Cache TypeScript artifacts via the report field - this enables incremental compilation
        report=typescript_artifacts_digest,
        output_simplifier=global_options.output_simplifier(),
    )

    return check_result


async def _typecheck_typescript_files(
    field_sets: tuple[TypeScriptCheckFieldSet | TypeScriptTestCheckFieldSet, ...],
    subsystem: TypeScriptSubsystem,
    tool_name: str,
    global_options: GlobalOptions,
) -> CheckResults:
    if subsystem.skip:
        return CheckResults([], checker_name=tool_name)

    if not field_sets:
        return CheckResults([], checker_name=tool_name)

    target_sources = await concurrently(
        hydrate_sources(HydrateSourcesRequest(field_set.sources), **implicitly())
        for field_set in field_sets
    )

    all_source_files: list[str] = []
    target_addresses = set()
    for i, sources in enumerate(target_sources):
        all_source_files.extend(sources.snapshot.files)
        target_addresses.add(field_sets[i].address)

    if not all_source_files:
        return CheckResults([], checker_name=tool_name)

    all_projects = await Get(AllNodeJSProjects)
    owning_packages = await concurrently(
        find_owning_package(OwningNodePackageRequest(address), **implicitly())
        for address in target_addresses
    )

    # Group targets by their containing NodeJS project
    projects_to_check: dict[NodeJSProject, list[object]] = {}
    for i, owning_package in enumerate(owning_packages):
        address = list(target_addresses)[i]
        if owning_package.target:
            package_directory = owning_package.target.address.spec_path
            owning_project = all_projects.project_for_directory(package_directory)
            if owning_project:
                if owning_project not in projects_to_check:
                    projects_to_check[owning_project] = []
                projects_to_check[owning_project].append(address)

    if not projects_to_check:
        logger.warning(f"No NodeJS projects found for TypeScript targets: {target_addresses}")
        return CheckResults([], checker_name=tool_name)

    # Check all projects concurrently
    project_results = await concurrently(
        _typecheck_single_project(project, subsystem, global_options)
        for project in projects_to_check.keys()
    )

    return CheckResults(project_results, checker_name=tool_name)


@rule(desc="Check TypeScript compilation", level=LogLevel.DEBUG)
async def typecheck_typescript(
    request: TypeScriptCheckRequest, subsystem: TypeScriptSubsystem, global_options: GlobalOptions
) -> CheckResults:
    return await _typecheck_typescript_files(
        request.field_sets, subsystem, request.tool_name, global_options
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(CheckRequest, TypeScriptCheckRequest),
    ]
