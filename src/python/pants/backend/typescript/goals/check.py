# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from pants.backend.javascript.nodejs_project import AllNodeJSProjects
from pants.backend.javascript.package_json import (
    AllPackageJson,
    OwningNodePackageRequest,
    all_package_json,
    find_owning_package,
)
from pants.backend.javascript.resolve import ChosenNodeResolve, RequestNodeResolve
from pants.backend.javascript.subsystems.nodejs_tool import NodeJSToolRequest
from pants.backend.typescript.subsystem import TypeScriptSubsystem
from pants.backend.typescript.target_types import TypeScriptSourceField, TypeScriptTestSourceField
from pants.backend.typescript.tsconfig import AllTSConfigs, TSConfig, construct_effective_ts_configs
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
    Target,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobalOptions
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pants.backend.javascript.nodejs_project import NodeJSProject


_TYPESCRIPT_OUTPUT_EXTENSIONS = [
    ".js",
    ".mjs",
    ".cjs",
    ".d.ts",
    ".d.mts",
    ".d.cts",
    ".js.map",
    ".mjs.map",
    ".cjs.map",
    ".d.ts.map",
    ".d.mts.map",
    ".d.cts.map",
    ".tsbuildinfo",
]


def _build_workspace_tsconfig_map(workspaces, all_ts_configs) -> dict[str, TSConfig]:
    workspace_dir_map = {os.path.normpath(pkg.root_dir): pkg for pkg in workspaces}
    workspace_dir_to_tsconfig: dict[str, TSConfig] = {}

    # Only consider tsconfig.json files (exclude tsconfig.build.json, tsconfig.test.json, etc.)
    # since tsc only reads tsconfig.json by default and we don't support -p flag
    tsconfig_json_files = [
        cfg for cfg in all_ts_configs 
        if os.path.basename(cfg.path) == 'tsconfig.json'
    ]

    for ts_config in tsconfig_json_files:
        config_dir = os.path.normpath(os.path.dirname(ts_config.path))

        if config_dir in workspace_dir_map:
            workspace_dir_to_tsconfig[config_dir] = ts_config

    return workspace_dir_to_tsconfig


def _calculate_resolved_output_dirs(
    project: NodeJSProject, all_ts_configs, project_root_path: Path
) -> set[str]:
    workspace_dir_to_tsconfig = _build_workspace_tsconfig_map(
        project.workspaces, all_ts_configs
    )
    
    resolved_output_dirs = set()

    for workspace_pkg in project.workspaces:
        workspace_pkg_path = Path(workspace_pkg.root_dir)

        if workspace_pkg_path == project_root_path:
            pkg_prefix = ""
        else:
            relative_path = workspace_pkg_path.relative_to(project_root_path)
            pkg_prefix = f"{relative_path.as_posix()}/"

        pkg_tsconfig = workspace_dir_to_tsconfig.get(os.path.normpath(workspace_pkg.root_dir))

        if pkg_tsconfig and pkg_tsconfig.out_dir:
            pkg_tsconfig.validate_outdir()
            resolved_out_dir = f"{pkg_prefix}{pkg_tsconfig.out_dir.lstrip('./')}"
            resolved_output_dirs.add(resolved_out_dir)

    return resolved_output_dirs


def _get_typescript_artifact_globs(
    project: NodeJSProject, resolved_output_dirs: set[str]
) -> list[str]:
    globs = []
    project_root_path = Path(project.root_dir)

    for resolved_dir in resolved_output_dirs:
        for ext in _TYPESCRIPT_OUTPUT_EXTENSIONS:
            globs.append(f"{resolved_dir}/**/*{ext}")

    # Handle case where tsconfig.tsbuildinfo are output alongside tsconfig.json in each package
    for workspace_pkg in project.workspaces:
        workspace_pkg_path = Path(workspace_pkg.root_dir)
        if workspace_pkg_path == project_root_path:
            pkg_prefix = ""
        else:
            relative_path = workspace_pkg_path.relative_to(project_root_path)
            pkg_prefix = f"{relative_path.as_posix()}/"
        globs.append(f"{pkg_prefix}tsconfig.tsbuildinfo")

    return globs


async def _load_cached_typescript_artifacts(
    artifact_globs: list[str]
) -> Digest:
    cached_artifacts = await path_globs_to_digest(
        PathGlobs(artifact_globs, glob_match_error_behavior=GlobMatchErrorBehavior.ignore),
        **implicitly(),
    )
    return cached_artifacts


async def _extract_typescript_artifacts_for_caching(
    process_output_digest: Digest,
    artifact_globs: list[str],
) -> Digest:
    artifacts_digest = await Get(
        Digest,
        DigestSubset(
            process_output_digest,
            PathGlobs(artifact_globs, glob_match_error_behavior=GlobMatchErrorBehavior.ignore),
        ),
    )

    return artifacts_digest


async def _collect_config_files_for_project(
    project: NodeJSProject,
    typescript_targets: list[Target],
    all_package_json: AllPackageJson,
    all_ts_configs: AllTSConfigs,
) -> list[str]:
    """Collect all configuration files needed for TypeScript compilation in a project.

    This includes:
    - package.json files (for dependencies and module resolution)
    - tsconfig.json files (for TypeScript compiler configuration)
    - file() targets that are dependencies of TypeScript targets
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

    # Add file() targets that are dependencies of TypeScript targets
    # Note: Package manager config files
    # (.npmrc, .pnpmrc, pnpm-workspace.yaml) should be dependencies of package_json targets
    # since they affect package installation, not TypeScript compilation directly.
    if typescript_targets:
        typescript_addresses = [target.address for target in typescript_targets]
        transitive_targets = await Get(
            TransitiveTargets, TransitiveTargetsRequest(typescript_addresses)
        )

        for target in transitive_targets.closure:
            if target.has_field(FileSourceField):
                file_path = target[FileSourceField].file_path
                if file_path.startswith(project.root_dir):
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
    for target, owning_package in zip(typescript_targets, typescript_owning_packages):
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
    all_package_jsons, all_ts_configs = await concurrently(
        all_package_json(),
        construct_effective_ts_configs(),
    )

    config_files = await _collect_config_files_for_project(
        project, project_typescript_targets, all_package_jsons, all_ts_configs
    )

    # Validate that all TypeScript configurations have explicit outDir settings
    project_ts_configs = [
        config for config in all_ts_configs if config.path.startswith(project.root_dir)
    ]
    for ts_config in project_ts_configs:
        ts_config.validate_outdir()

    # Get config file digests
    config_digest = (
        await path_globs_to_digest(
            PathGlobs(config_files, glob_match_error_behavior=GlobMatchErrorBehavior.ignore),
            **implicitly(),
        )
        if config_files
        else EMPTY_DIGEST
    )

    # Calculate resolved output directories once for all operations
    project_root_path = Path(project.root_dir)
    resolved_output_dirs = _calculate_resolved_output_dirs(
        project, all_ts_configs, project_root_path
    )
    
    # Calculate artifact globs using the resolved output directories
    artifact_globs = _get_typescript_artifact_globs(project, resolved_output_dirs)

    # Include cached .tsbuildinfo files and output files for incremental compilation
    # TypeScript --build uses these files to skip unchanged packages
    cached_typescript_artifacts = await _load_cached_typescript_artifacts(
        artifact_globs
    )

    # Merge workspace sources, config files, and cached TypeScript artifacts
    all_digests = (
        [all_workspace_sources]
        + ([config_digest] if config_digest != EMPTY_DIGEST else [])
        + ([cached_typescript_artifacts] if cached_typescript_artifacts != EMPTY_DIGEST else [])
    )
    input_digest = await merge_digests(MergeDigests(all_digests))

    # Use --build to compile all projects in workspace with project references
    args = ("--build",)

    tool_request = subsystem.request(
        args=args,
        input_digest=input_digest,
        description=f"Type-check TypeScript project {project.root_dir} ({len(project_typescript_targets)} targets)",
        level=LogLevel.DEBUG,
    )

    # Determine which resolve to use for this TypeScript project
    # Use the project's root directory to get the correct resolve
    # - For monorepos: all workspaces share the parent project's lockfile/resolve
    # - For standalone projects: the project root contains the lockfile/resolve
    project_address = Address(project.root_dir)
    project_resolve = await Get(ChosenNodeResolve, RequestNodeResolve(project_address))

    # Override the resolve to use the project's resolve instead of default
    tool_request_with_resolve = replace(tool_request, resolve=project_resolve.resolve_name)

    # Execute TypeScript type checking with the project's resolve
    process = await Get(Process, NodeJSToolRequest, tool_request_with_resolve)

    # Set working directory to the project root where tsconfig.json is located
    working_directory = project.root_dir if project.root_dir != "." else None

    # TypeScript composite projects generate .tsbuildinfo files in the project root by default
    output_directories = (".",) + tuple(sorted(resolved_output_dirs))

    process_with_outputs = replace(
        process,
        working_directory=working_directory,
        output_directories=output_directories,
    )

    result = await execute_process(process_with_outputs, **implicitly())

    # Cache TypeScript incremental build artifacts for faster subsequent runs
    # TypeScript --build generates .tsbuildinfo files and output files that enable incremental compilation
    typescript_artifacts_digest = await _extract_typescript_artifacts_for_caching(
        result.output_digest, artifact_globs
    )

    # Convert to CheckResult with caching support - single result for the project
    check_result = CheckResult.from_fallible_process_result(
        result,
        partition_description=f"TypeScript check on {project.root_dir} ({len(project_typescript_targets)} targets)",
        # Store TypeScript incremental artifacts in the report field for output to dist directory
        # Note: The report field is used to save tool outputs to the user's dist directory,
        # not for caching between runs (Pants handles incremental caching internally via digests)
        # See: write_reports() in multi_tool_goal_helper.py and mypy rules.py for examples
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
    projects_to_check: dict[NodeJSProject, list[Address]] = {}
    for address, owning_package in zip(target_addresses, owning_packages):
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

    # Check all projects
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
