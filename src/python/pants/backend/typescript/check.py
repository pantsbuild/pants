# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from pants.backend.javascript.nodejs_project import AllNodeJSProjects
from pants.backend.javascript.package_json import AllPackageJson, OwningNodePackageRequest, find_owning_package
from pants.backend.javascript.resolve import ChosenNodeResolve, RequestNodeResolve
from pants.backend.javascript.subsystems.nodejs_tool import NodeJSToolRequest
from pants.backend.typescript.subsystem import TypeScriptSubsystem
from pants.backend.typescript.tsconfig import AllTSConfigs
from pants.backend.typescript.target_types import (
    TypeScriptSourceField,
    TypeScriptSourceTarget,
    TypeScriptTestSourceField,
)
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.core.target_types import FileSourceField
from pants.engine.fs import EMPTY_DIGEST, Digest, DigestContents, DigestSubset, GlobMatchErrorBehavior, PathGlobs
from pants.engine.internals.graph import hydrate_sources, HydrateSourcesRequest
from pants.engine.internals.native_engine import MergeDigests
from pants.engine.internals.selectors import Get, concurrently
from pants.engine.intrinsics import execute_process, merge_digests, path_globs_to_digest
from pants.engine.process import Process
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import AllTargets, BoolField, FieldSet, Target, TransitiveTargets, TransitiveTargetsRequest
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobalOptions
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


async def _load_cached_typescript_artifacts(project) -> Digest:
    """Load cached .tsbuildinfo files and output files for incremental TypeScript compilation."""
    cache_globs = []
    for workspace_pkg in project.workspaces:
        # Cache .tsbuildinfo files for incremental state
        cache_globs.append(f"{workspace_pkg.root_dir}/tsconfig.tsbuildinfo")
        # Cache output directories that TypeScript --build generates
        cache_globs.append(f"{workspace_pkg.root_dir}/dist/**/*")
        
    cached_artifacts = await path_globs_to_digest(
        PathGlobs(cache_globs, glob_match_error_behavior=GlobMatchErrorBehavior.ignore),
        **implicitly()
    )
    
    if cached_artifacts != EMPTY_DIGEST:
        artifact_contents = await Get(DigestContents, Digest, cached_artifacts)
        logger.info(f"DEBUG: Found {len(artifact_contents)} cached TypeScript artifacts for incremental compilation")
        for artifact in sorted(artifact_contents, key=lambda f: f.path):
            logger.info(f"DEBUG:   {artifact.path}")
    else:
        logger.info(f"DEBUG: No cached TypeScript artifacts found - this will be a full compilation")
    
    return cached_artifacts


async def _extract_typescript_artifacts_for_caching(project, process_output_digest: Digest) -> Digest:
    """Extract .tsbuildinfo files and output files from TypeScript compilation for caching."""
    output_globs = []
    for workspace_pkg in project.workspaces:
        # Extract .tsbuildinfo files for incremental state
        output_globs.append(f"{workspace_pkg.root_dir}/tsconfig.tsbuildinfo")
        # Extract output directories that TypeScript --build generates
        output_globs.append(f"{workspace_pkg.root_dir}/dist/**/*")
    
    artifacts_digest = await Get(
        Digest,
        DigestSubset(
            process_output_digest,
            PathGlobs(
                output_globs, 
                glob_match_error_behavior=GlobMatchErrorBehavior.ignore
            )
        )
    )
    
    # DEBUG: Log captured artifacts
    if artifacts_digest != EMPTY_DIGEST:
        artifact_contents = await Get(DigestContents, Digest, artifacts_digest)
        logger.info(f"DEBUG: Cached {len(artifact_contents)} TypeScript artifacts for incremental compilation")
        for artifact in sorted(artifact_contents, key=lambda f: f.path):
            logger.info(f"DEBUG:   {artifact.path}")
    else:
        logger.info(f"DEBUG: No TypeScript artifacts generated for project {project.root_dir}")
    
    return artifacts_digest


class SkipTypeScriptCheckField(BoolField):
    alias = "skip_typescript_check"
    default = False
    help = "If true, don't run TypeScript type checking on this target's code."


@dataclass(frozen=True)
class TypeScriptCheckFieldSet(FieldSet):
    required_fields = (TypeScriptSourceField,)
    
    sources: TypeScriptSourceField
    
    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipTypeScriptCheckField).value


@dataclass(frozen=True) 
class TypeScriptTestCheckFieldSet(FieldSet):
    required_fields = (TypeScriptTestSourceField,)
    
    sources: TypeScriptTestSourceField
    
    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipTypeScriptCheckField).value


class TypeScriptCheckRequest(CheckRequest):
    field_set_type = TypeScriptCheckFieldSet
    tool_name = TypeScriptSubsystem.options_scope


class TypeScriptTestCheckRequest(CheckRequest):
    field_set_type = TypeScriptTestCheckFieldSet
    tool_name = TypeScriptSubsystem.options_scope


async def _typecheck_single_project(
    project,  # NodeJSProject - can't import due to circular imports
    subsystem: TypeScriptSubsystem,
    global_options: GlobalOptions,
) -> CheckResult:
    """Type check a single TypeScript project."""
    logger.info(f"DEBUG: TypeScript check for project: {project.root_dir}")
    
    # PR_NOTE: Find all TypeScript targets within this project using Pants' target knowledge
    # This replaces glob-based file discovery with proper target-based source discovery
    all_targets = await Get(AllTargets)
    
    # Find all TypeScript targets, excluding those that opt out
    # NOTE: This differs from other backends that handle opt-out via field set filtering
    # TypeScript requires project-level checking, so we filter at the target level
    typescript_targets = [
        target for target in all_targets 
        if (target.has_field(TypeScriptSourceField) or target.has_field(TypeScriptTestSourceField))
        and not (TypeScriptCheckFieldSet.opt_out(target) or TypeScriptTestCheckFieldSet.opt_out(target))
    ]
    
    # Get owning packages for all TypeScript targets concurrently
    typescript_owning_packages = await concurrently(
        find_owning_package(OwningNodePackageRequest(target.address), **implicitly())
        for target in typescript_targets
    )
    
    # Filter to targets that belong to the current project
    project_typescript_targets = []
    for i, owning_package in enumerate(typescript_owning_packages):
        target = typescript_targets[i]
        if owning_package.target:
            package_directory = owning_package.target.address.spec_path
            all_projects = await Get(AllNodeJSProjects)
            target_project = all_projects.project_for_directory(package_directory)
            if target_project == project:
                project_typescript_targets.append(target)
    
    logger.info(f"DEBUG: Found {len(project_typescript_targets)} TypeScript targets in project")
    
    # Get source files from all TypeScript targets in the project
    if project_typescript_targets:
        workspace_target_sources = await concurrently(
            hydrate_sources(HydrateSourcesRequest(
                target[TypeScriptSourceField] if target.has_field(TypeScriptSourceField) 
                else target[TypeScriptTestSourceField]
            ), **implicitly())
            for target in project_typescript_targets
        )
        
        # Merge all workspace target sources
        all_workspace_digests = [sources.snapshot.digest for sources in workspace_target_sources]
        all_workspace_sources = await merge_digests(MergeDigests(all_workspace_digests))
        
        # DEBUG: Log what source files were captured
        source_contents = await Get(DigestContents, Digest, all_workspace_sources)
        logger.info(f"DEBUG: Captured {len(source_contents)} source files from project targets:")
        for file_content in sorted(source_contents, key=lambda f: f.path):
            logger.info(f"DEBUG:   {file_content.path}")
    else:
        logger.warning(f"No TypeScript targets found in project {project.root_dir}")
        return CheckResult(
            exit_code=0,
            stdout="",
            stderr="",
            partition_description=f"TypeScript check on {project.root_dir} (no targets)",
        )
    
    # PR_NOTE: Dynamically discover configuration files using Pants' target-based discovery
    # This replaces hard-coded config file paths with comprehensive target-based discovery
    all_package_json = await Get(AllPackageJson)
    all_ts_configs = await Get(AllTSConfigs)
    
    # Find package.json files within this project
    project_package_jsons = [
        pkg for pkg in all_package_json
        if pkg.root_dir.startswith(project.root_dir)
    ]
    
    # Find tsconfig.json files within this project
    project_ts_configs = [
        config for config in all_ts_configs
        if config.path.startswith(project.root_dir)
    ]
    
    # Build list of config file paths from discovered targets
    config_files = []
    
    # Add discovered package.json files
    for pkg_json in project_package_jsons:
        config_files.append(pkg_json.file)
    
    # Add discovered tsconfig.json files  
    for ts_config in project_ts_configs:
        config_files.append(ts_config.path)
    
    # PR_NOTE: Use target-based discovery for package manager config files
    # Users must declare config files as file() targets in BUILD files
    # TODO: Future enhancement - JavaScript backend should provide automatic target generation
    # for .npmrc, .pnpmrc, pnpm-workspace.yaml (see FUTURE_ENHANCEMENTS.md)
    
    # Find config files declared as explicit file targets
    from pants.build_graph.address import Address
    project_root_address = Address(project.root_dir)
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest([project_root_address]))
    
    # Look for package manager config files declared as targets
    config_file_targets = []
    for target in transitive_targets.closure:
        if target.has_field(FileSourceField):
            file_path = target[FileSourceField].file_path
            file_name = file_path.split('/')[-1]
            if file_name in ('.npmrc', '.pnpmrc', 'pnpm-workspace.yaml') and file_path.startswith(project.root_dir):
                config_file_targets.append(file_path)
    
    config_files.extend(config_file_targets)
    
    logger.info(f"DEBUG: Found {len(config_file_targets)} config file targets")
    
    logger.info(f"DEBUG: Configuration files discovered: {len(project_package_jsons)} package.json, {len(project_ts_configs)} tsconfig.json")
    logger.info(f"DEBUG: Total configuration files to include: {config_files}")
    
    # Get config file digests
    config_digests = []
    for config_file in config_files:
        config_digest = await path_globs_to_digest(
            PathGlobs([config_file], glob_match_error_behavior=GlobMatchErrorBehavior.ignore),
            **implicitly()
        )
        config_digests.append(config_digest)
    
    # Include cached .tsbuildinfo files and output files for incremental compilation
    # TypeScript --build uses these files to skip unchanged packages
    cached_typescript_artifacts = await _load_cached_typescript_artifacts(project)
    
    # Merge workspace sources, config files, and cached TypeScript artifacts
    all_digests = [all_workspace_sources] + config_digests + ([cached_typescript_artifacts] if cached_typescript_artifacts != EMPTY_DIGEST else [])
    input_digest = await merge_digests(MergeDigests(all_digests))
    
    # DEBUG: Log final input_digest contents  
    final_contents = await Get(DigestContents, Digest, input_digest)
    logger.info(f"DEBUG: Final input_digest contains {len(final_contents)} files:")
    for file_content in sorted(final_contents, key=lambda f: f.path):
        logger.info(f"DEBUG:   {file_content.path}")
    
    # Use --build to compile all projects in workspace with project references
    args = ("--build",)
    
    # Determine which resolve to use for this TypeScript project
    # Find the root package within this project to get the resolve
    root_package = None
    for workspace_pkg in project.workspaces:
        if workspace_pkg.root_dir == project.root_dir:
            root_package = workspace_pkg
            break
    
    if not root_package:
        # If no root package found, use the first workspace package
        root_package = list(project.workspaces)[0]
    
    # We need the package target address, not the PackageJson. 
    # For now, construct it based on the directory
    from pants.build_graph.address import Address
    package_address = Address(root_package.root_dir)
    project_resolve = await Get(ChosenNodeResolve, RequestNodeResolve(package_address))
    
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
    process_with_workdir = replace(process, working_directory=working_directory) if working_directory else process
    
    result = await execute_process(process_with_workdir, **implicitly())
    
    # Cache TypeScript incremental build artifacts for faster subsequent runs
    # TypeScript --build generates .tsbuildinfo files and output files that enable incremental compilation
    typescript_artifacts_digest = await _extract_typescript_artifacts_for_caching(project, result.output_digest)
    
    # Convert to CheckResult with caching support - single result for the project
    check_result = CheckResult.from_fallible_process_result(
        result,
        partition_description=f"TypeScript check on {project.root_dir} ({len(project_typescript_targets)} targets)",
        # Cache TypeScript artifacts via the report field - this enables incremental compilation
        report=typescript_artifacts_digest,
        # PR_NOTE: Use output simplifier to clean up temporary paths in error messages
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
    
    # Get source files for the specific field sets being checked
    target_sources = await concurrently(
        hydrate_sources(HydrateSourcesRequest(field_set.sources), **implicitly())
        for field_set in field_sets
    )
    
    # Collect source files and their addresses
    all_source_files = []
    target_addresses = set()
    for i, sources in enumerate(target_sources):
        all_source_files.extend(sources.snapshot.files)
        target_addresses.add(field_sets[i].address)
    
    if not all_source_files:
        return CheckResults([], checker_name=tool_name)
    
    # PR_NOTE: Discover which NodeJS projects contain the TypeScript targets
    # This replaces the hard-coded examples/** path approach with dynamic project discovery
    all_projects = await Get(AllNodeJSProjects)
    
    # Find owning packages for all TypeScript targets
    owning_packages = await concurrently(
        find_owning_package(OwningNodePackageRequest(address), **implicitly())
        for address in target_addresses
    )
    
    # Group targets by their containing NodeJS project
    projects_to_check = {}
    for i, owning_package in enumerate(owning_packages):
        address = list(target_addresses)[i]
        if owning_package.target:
            # Find which NodeJS project contains this package
            package_directory = owning_package.target.address.spec_path
            owning_project = all_projects.project_for_directory(package_directory)
            if owning_project:
                if owning_project not in projects_to_check:
                    projects_to_check[owning_project] = []
                projects_to_check[owning_project].append(address)
    
    if not projects_to_check:
        logger.warning(f"No NodeJS projects found for TypeScript targets: {target_addresses}")
        return CheckResults([], checker_name=tool_name)
    
    # PR_NOTE: Multi-project support - check each project concurrently
    # This replaces the single project limitation with concurrent multi-project execution
    logger.info(f"DEBUG: TypeScript check across {len(projects_to_check)} projects: {[proj.root_dir for proj in projects_to_check.keys()]}")
    
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
    return await _typecheck_typescript_files(request.field_sets, subsystem, request.tool_name, global_options)



def rules():
    from pants.backend.typescript.target_types import (
        TypeScriptSourcesGeneratorTarget,
        TypeScriptTestTarget,
        TypeScriptTestsGeneratorTarget,
    )
    
    return [
        *collect_rules(),
        UnionRule(CheckRequest, TypeScriptCheckRequest),
        # Register skip field on all TypeScript target types
        TypeScriptSourceTarget.register_plugin_field(SkipTypeScriptCheckField),
        TypeScriptSourcesGeneratorTarget.register_plugin_field(SkipTypeScriptCheckField),
        TypeScriptTestTarget.register_plugin_field(SkipTypeScriptCheckField),
        TypeScriptTestsGeneratorTarget.register_plugin_field(SkipTypeScriptCheckField),
    ]
