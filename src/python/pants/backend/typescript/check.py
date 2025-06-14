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
from pants.engine.fs import Digest, DigestContents, GlobMatchErrorBehavior, PathGlobs
from pants.engine.internals.graph import hydrate_sources, HydrateSourcesRequest
from pants.engine.internals.native_engine import MergeDigests
from pants.engine.internals.selectors import Get, concurrently
from pants.engine.intrinsics import execute_process, merge_digests, path_globs_to_digest
from pants.engine.process import Process
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import AllTargets, BoolField, FieldSet, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


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


async def _typecheck_typescript_files(
    field_sets: tuple[TypeScriptCheckFieldSet | TypeScriptTestCheckFieldSet, ...],
    subsystem: TypeScriptSubsystem,
    tool_name: str
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
    
    # For now, handle single project case (Phase 2 scope)
    if len(projects_to_check) > 1:
        project_names = [proj.root_dir for proj in projects_to_check.keys()]
        raise ValueError(f"TypeScript check across multiple projects not yet supported. Found projects: {project_names}")
    
    project = list(projects_to_check.keys())[0]
    logger.info(f"DEBUG: TypeScript check for project: {project.root_dir}")
    
    # PR_NOTE: Find all TypeScript targets within this project using Pants' target knowledge
    # This replaces glob-based file discovery with proper target-based source discovery
    all_targets = await Get(AllTargets)
    
    # Find all TypeScript targets
    typescript_targets = [
        target for target in all_targets 
        if target.has_field(TypeScriptSourceField) or target.has_field(TypeScriptTestSourceField)
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
        return CheckResults([], checker_name=tool_name)
    
    # PR_NOTE: Dynamically discover configuration files using Pants' target-based discovery
    # This replaces hard-coded config file paths with AllPackageJson and AllTSConfigs discovery
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
    
    # Add package manager specific workspace config files (still need globs for these)
    if project.package_manager.name == "pnpm":
        config_files.append(f"{project.root_dir}/pnpm-workspace.yaml")
    
    # Add .npmrc and .pnpmrc if they exist
    config_files.extend([
        f"{project.root_dir}/.npmrc",
        f"{project.root_dir}/.pnpmrc"
    ])
    
    logger.info(f"DEBUG: Configuration files discovered from targets: {len(project_package_jsons)} package.json, {len(project_ts_configs)} tsconfig.json")
    logger.info(f"DEBUG: Total configuration files to include: {config_files}")
    
    # Get config file digests
    config_digests = []
    for config_file in config_files:
        try:
            config_digest = await path_globs_to_digest(
                PathGlobs([config_file], glob_match_error_behavior=GlobMatchErrorBehavior.ignore),
                **implicitly()
            )
            config_digests.append(config_digest)
        except Exception:
            # Skip missing config files
            continue
    
    # Merge workspace sources and config files (including .npmrc)
    all_digests = [all_workspace_sources] + config_digests
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
        description=f"Type-check TypeScript project {project.root_dir} ({len(field_sets)} targets)",
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
    
    # Convert to CheckResult - single result for all packages
    check_result = CheckResult.from_fallible_process_result(
        result,
        partition_description=f"TypeScript check on {len(field_sets)} targets",
    )
    
    return CheckResults([check_result], checker_name=tool_name)


@rule(desc="Check TypeScript compilation", level=LogLevel.DEBUG)
async def typecheck_typescript(
    request: TypeScriptCheckRequest, subsystem: TypeScriptSubsystem
) -> CheckResults:
    return await _typecheck_typescript_files(request.field_sets, subsystem, request.tool_name)


# @rule(desc="Check TypeScript test compilation", level=LogLevel.DEBUG)
# async def typecheck_typescript_tests(
#     request: TypeScriptTestCheckRequest, subsystem: TypeScriptSubsystem
# ) -> CheckResults:
#     return await _typecheck_typescript_files(request.field_sets, subsystem, request.tool_name)



def rules():
    return [
        *collect_rules(),
        UnionRule(CheckRequest, TypeScriptCheckRequest),
        # UnionRule(CheckRequest, TypeScriptTestCheckRequest),
        TypeScriptSourceTarget.register_plugin_field(SkipTypeScriptCheckField),
        # TypeScriptTestTarget.register_plugin_field(SkipTypeScriptCheckField),
    ]
