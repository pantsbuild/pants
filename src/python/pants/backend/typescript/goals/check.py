# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

from pants.backend.javascript.nodejs_project import AllNodeJSProjects, find_node_js_projects
from pants.backend.javascript.package_json import (
    AllPackageJson,
    OwningNodePackageRequest,
    PackageJson,
    all_package_json,
    find_owning_package,
)
from pants.backend.javascript.resolve import RequestNodeResolve, resolve_for_package
from pants.backend.javascript.subsystems.nodejs_tool import NodeJSToolRequest, prepare_tool_process
from pants.backend.javascript.target_types import JSRuntimeSourceField
from pants.backend.typescript.subsystem import TypeScriptSubsystem
from pants.backend.typescript.target_types import TypeScriptSourceField, TypeScriptTestSourceField
from pants.backend.typescript.tsconfig import AllTSConfigs, TSConfig, construct_effective_ts_configs
from pants.base.build_root import BuildRoot
from pants.build_graph.address import Address
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults, CheckSubsystem
from pants.core.target_types import FileSourceField
from pants.core.util_rules.system_binaries import CpBinary, FindBinary, MkdirBinary, TouchBinary
from pants.engine.fs import (
    EMPTY_DIGEST,
    CreateDigest,
    Digest,
    FileContent,
    GlobMatchErrorBehavior,
    PathGlobs,
)
from pants.engine.internals.graph import find_all_targets, hydrate_sources, transitive_targets
from pants.engine.internals.native_engine import MergeDigests
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import (
    create_digest,
    execute_process,
    merge_digests,
    path_globs_to_digest,
)
from pants.engine.process import Process
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import (
    AllTargets,
    FieldSet,
    HydrateSourcesRequest,
    Target,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobalOptions
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet

if TYPE_CHECKING:
    from pants.backend.javascript.nodejs_project import NodeJSProject

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CreateTscWrapperScriptRequest:
    project: NodeJSProject
    package_output_dirs: tuple[str, ...]
    build_root: BuildRoot
    named_cache_sandbox_mount_dir: str
    tsc_wrapper_filename: str


@dataclass(frozen=True)
class TypeScriptCheckFieldSet(FieldSet):
    required_fields = (JSRuntimeSourceField,)

    sources: JSRuntimeSourceField


class TypeScriptCheckRequest(CheckRequest):
    field_set_type = TypeScriptCheckFieldSet
    tool_name = TypeScriptSubsystem.options_scope


def _build_workspace_tsconfig_map(
    workspaces: FrozenOrderedSet[PackageJson], all_ts_configs: list[TSConfig]
) -> dict[str, TSConfig]:
    workspace_dir_map = {os.path.normpath(pkg.root_dir): pkg for pkg in workspaces}
    workspace_dir_to_tsconfig: dict[str, TSConfig] = {}

    # Only consider tsconfig.json files (exclude tsconfig.build.json, tsconfig.test.json, etc.)
    # since tsc only reads tsconfig.json by default and we don't support the `--project` flag currently
    # Additionally, TSConfig class only supports tsconfig.json.
    tsconfig_json_files = [
        cfg for cfg in all_ts_configs if os.path.basename(cfg.path) == "tsconfig.json"
    ]

    for ts_config in tsconfig_json_files:
        config_dir = os.path.normpath(os.path.dirname(ts_config.path))

        if config_dir in workspace_dir_map:
            workspace_dir_to_tsconfig[config_dir] = ts_config

    return workspace_dir_to_tsconfig


def _collect_package_output_dirs(
    project: NodeJSProject, project_ts_configs: list[TSConfig], project_root_path: Path
) -> tuple[str, ...]:
    workspace_dir_to_tsconfig = _build_workspace_tsconfig_map(
        project.workspaces, project_ts_configs
    )

    package_output_dirs: OrderedSet[str] = OrderedSet()
    for workspace_pkg in project.workspaces:
        workspace_pkg_path = Path(workspace_pkg.root_dir)

        if workspace_pkg_path == project_root_path:
            pkg_prefix = ""
        else:
            relative_path = workspace_pkg_path.relative_to(project_root_path)
            pkg_prefix = f"{relative_path.as_posix()}/"

        pkg_tsconfig = workspace_dir_to_tsconfig.get(os.path.normpath(workspace_pkg.root_dir))

        if pkg_tsconfig and pkg_tsconfig.out_dir:
            resolved_out_dir = f"{pkg_prefix}{pkg_tsconfig.out_dir.lstrip('./')}"
            package_output_dirs.add(resolved_out_dir)

    return tuple(package_output_dirs)


def _collect_project_configs(
    project: NodeJSProject, all_package_jsons: AllPackageJson, all_ts_configs: AllTSConfigs
) -> tuple[list, list[TSConfig]]:
    project_package_jsons = [
        pkg for pkg in all_package_jsons if pkg.root_dir.startswith(project.root_dir)
    ]
    project_ts_configs = [
        config for config in all_ts_configs if config.path.startswith(project.root_dir)
    ]
    return project_package_jsons, project_ts_configs


async def _collect_config_files_for_project(
    project: NodeJSProject,
    targets: list[Target],
    project_package_jsons: list,
    project_ts_configs: list[TSConfig],
) -> list[str]:
    config_files = []

    for pkg_json in project_package_jsons:
        config_files.append(pkg_json.file)

    for ts_config in project_ts_configs:
        config_files.append(ts_config.path)

    # Add file() targets that are dependencies of JS/TS targets
    # Note: Package manager config files
    # (.npmrc, .pnpmrc, pnpm-workspace.yaml) should be dependencies of package_json targets
    # since they affect package installation, not TypeScript compilation directly.
    target_addresses = [target.address for target in targets]
    transitive_targets_result = await transitive_targets(
        TransitiveTargetsRequest(target_addresses), **implicitly()
    )

    for target in transitive_targets_result.closure:
        if target.has_field(FileSourceField):
            file_path = target[FileSourceField].file_path
            if file_path.startswith(project.root_dir):
                config_files.append(file_path)

    return config_files


@rule
async def create_tsc_wrapper_script(
    request: CreateTscWrapperScriptRequest,
    cp_binary: CpBinary,
    mkdir_binary: MkdirBinary,
    find_binary: FindBinary,
    touch_binary: TouchBinary,
) -> Digest:
    project = request.project
    package_output_dirs = request.package_output_dirs
    build_root = request.build_root
    named_cache_sandbox_mount_dir = request.named_cache_sandbox_mount_dir
    tsc_wrapper_filename = request.tsc_wrapper_filename

    project_abs_path = os.path.join(build_root.path, project.root_dir)
    cache_key = sha256(project_abs_path.encode()).hexdigest()

    project_depth = len([p for p in project.root_dir.strip("/").split("/") if p])
    cache_relative_path = (
        "../" * project_depth + named_cache_sandbox_mount_dir
        if project_depth > 0
        else named_cache_sandbox_mount_dir
    )
    project_cache_subdir = f"{cache_relative_path}/{cache_key}"

    package_dirs = []
    for workspace_pkg in project.workspaces:
        if workspace_pkg.root_dir != project.root_dir:
            package_relative = workspace_pkg.root_dir.removeprefix(f"{project.root_dir}/")
            package_dirs.append(package_relative)
        else:
            package_dirs.append(".")
    package_dirs_str = " ".join(f'"{d}"' for d in package_dirs)
    output_dirs_str = " ".join(f'"{d}"' for d in package_output_dirs)

    script_content = f"""#!/bin/sh
# TypeScript incremental compilation cache wrapper

# All source files in sandbox have mtime as at sandbox creation (e.g. when the process started).
# Without any special handling, tsc will do a fast immediate rebuild (without checking tsbuildinfo metadata).
# (tsc outputs: "Project 'tsconfig.json' is out of date because output 'tsconfig.tsbuildinfo' is older than input 'tsconfig.json'")
# What we want: tsconfig (oldest), tsbuildinfo (newer), source files (newest).
# See also https://github.com/microsoft/TypeScript/issues/54563

set -e

CP_BIN="{cp_binary.path}"
MKDIR_BIN="{mkdir_binary.path}"
FIND_BIN="{find_binary.path}"
TOUCH_BIN="{touch_binary.path}"

PROJECT_CACHE_SUBDIR="{project_cache_subdir}"

# Ensure cache directory exists (it won't on first run)
"$MKDIR_BIN" -p "$PROJECT_CACHE_SUBDIR" > /dev/null 2>&1

# Copy cached files to working directory
"$CP_BIN" -a "$PROJECT_CACHE_SUBDIR/." . > /dev/null 2>&1

# Make tsconfig files oldest
# This could be improved by passing a list of tsconfig files, but that might be best done if/when we have a Target for tsconfig files.
"$FIND_BIN" . -type f -name "tsconfig*.json" -exec "$TOUCH_BIN" -t 202001010000 {{}} +

# Run tsc
"$@"

# Update cache
# Copy .tsbuildinfo files located at package root to cache
for package_dir in {package_dirs_str}; do
    for tsbuildinfo_file in "$package_dir"/*.tsbuildinfo; do
        if [ -f "$tsbuildinfo_file" ]; then
            "$MKDIR_BIN" -p "$PROJECT_CACHE_SUBDIR/$package_dir"
            "$CP_BIN" "$tsbuildinfo_file" "$PROJECT_CACHE_SUBDIR/$package_dir/"
        fi
    done
done

# Copy output directories to cache
# (the output files are needed because tsc checks them against tsbuildinfo hashes when determining if a rebuild is required)
for output_dir in {output_dirs_str}; do
    if [ -d "$output_dir" ]; then
        output_parent="$(dirname "$output_dir")"
        "$MKDIR_BIN" -p "$PROJECT_CACHE_SUBDIR/$output_parent"
        "$CP_BIN" -r "$output_dir" "$PROJECT_CACHE_SUBDIR/$output_parent/"
    fi
done
"""

    script_digest = await create_digest(
        CreateDigest(
            [
                FileContent(
                    f"{project.root_dir}/{tsc_wrapper_filename}",
                    script_content.encode(),
                    is_executable=True,
                )
            ]
        ),
        **implicitly(),
    )

    return script_digest


async def _collect_project_targets(
    project: NodeJSProject,
    all_targets: AllTargets,
    all_projects: AllNodeJSProjects,
    project_ts_configs: list[TSConfig],
) -> list[Target]:
    has_check_js = any(
        ts_config.allow_js and ts_config.check_js for ts_config in project_ts_configs
    )

    if has_check_js:
        targets = [target for target in all_targets if target.has_field(JSRuntimeSourceField)]
    else:
        targets = [
            target
            for target in all_targets
            if (
                target.has_field(TypeScriptSourceField)
                or target.has_field(TypeScriptTestSourceField)
            )
        ]

    target_owning_packages = await concurrently(
        find_owning_package(OwningNodePackageRequest(target.address), **implicitly())
        for target in targets
    )

    project_targets = []
    for target, owning_package in zip(targets, target_owning_packages):
        if owning_package.target:
            package_directory = owning_package.target.address.spec_path
            target_project = all_projects.project_for_directory(package_directory)
            if target_project == project:
                project_targets.append(target)

    return project_targets


async def _hydrate_project_sources(
    project_targets: list[Target],
) -> Digest:
    workspace_target_sources = await concurrently(
        hydrate_sources(
            HydrateSourcesRequest(target[JSRuntimeSourceField]),
            **implicitly(),
        )
        for target in project_targets
    )

    return await merge_digests(
        MergeDigests([sources.snapshot.digest for sources in workspace_target_sources])
    )


async def _prepare_compilation_input(
    project: NodeJSProject,
    project_targets: list[Target],
    project_package_jsons: list,
    project_ts_configs: list[TSConfig],
    all_workspace_sources: Digest,
) -> Digest:
    config_files = await _collect_config_files_for_project(
        project, project_targets, project_package_jsons, project_ts_configs
    )
    for ts_config in project_ts_configs:
        ts_config.validate_outdir()

    config_digest = (
        await path_globs_to_digest(
            PathGlobs(config_files, glob_match_error_behavior=GlobMatchErrorBehavior.ignore),
            **implicitly(),
        )
        if config_files
        else EMPTY_DIGEST
    )

    return await merge_digests(MergeDigests([all_workspace_sources, config_digest]))


async def _prepare_tsc_build_process(
    project: NodeJSProject,
    subsystem: TypeScriptSubsystem,
    input_digest: Digest,
    package_output_dirs: tuple[str, ...],
    project_targets: list[Target],
    build_root: BuildRoot,
) -> Process:
    tsc_args = ("--build", *subsystem.extra_build_args)
    tsc_wrapper_filename = "__tsc_wrapper.sh"
    named_cache_local_dir = "typescript_cache"
    named_cache_sandbox_mount_dir = "._tsc_cache"

    project_resolve = await resolve_for_package(
        RequestNodeResolve(Address(project.root_dir)), **implicitly()
    )

    script_digest = await create_tsc_wrapper_script(
        CreateTscWrapperScriptRequest(
            project=project,
            package_output_dirs=package_output_dirs,
            build_root=build_root,
            named_cache_sandbox_mount_dir=named_cache_sandbox_mount_dir,
            tsc_wrapper_filename=tsc_wrapper_filename,
        ),
        **implicitly(),
    )

    tool_input = await merge_digests(MergeDigests([input_digest, script_digest]))

    tool_request = subsystem.request(
        args=tsc_args,
        input_digest=tool_input,
        description=f"Type-check TypeScript project {project.root_dir} ({len(project_targets)} targets)",
        level=LogLevel.DEBUG,
        project_caches=FrozenDict({named_cache_local_dir: named_cache_sandbox_mount_dir}),
    )

    # Uses the project's resolve as TypeScript execution requires project deps.
    tool_request_with_resolve: NodeJSToolRequest = replace(
        tool_request, resolve=project_resolve.resolve_name
    )

    process = await prepare_tool_process(tool_request_with_resolve, **implicitly())

    process_with_wrapper = replace(
        process,
        argv=(f"./{tsc_wrapper_filename}",) + process.argv,
        working_directory=project.root_dir,
        output_directories=package_output_dirs,
    )

    return process_with_wrapper


async def _typecheck_single_project(
    project: NodeJSProject,
    subsystem: TypeScriptSubsystem,
    check_subsystem: CheckSubsystem,
    global_options: GlobalOptions,
    all_targets: AllTargets,
    all_projects: AllNodeJSProjects,
    all_package_jsons: AllPackageJson,
    all_ts_configs: AllTSConfigs,
    build_root: BuildRoot,
) -> CheckResult:
    project_package_jsons, project_ts_configs = _collect_project_configs(
        project, all_package_jsons, all_ts_configs
    )

    project_targets = await _collect_project_targets(
        project, all_targets, all_projects, project_ts_configs
    )

    if not project_targets:
        return CheckResult(
            exit_code=0,
            stdout="",
            stderr="",
            partition_description=f"TypeScript check on {project.root_dir} (no targets)",
        )

    all_workspace_sources = await _hydrate_project_sources(project_targets)
    input_digest = await _prepare_compilation_input(
        project,
        project_targets,
        project_package_jsons,
        project_ts_configs,
        all_workspace_sources,
    )
    package_output_dirs = _collect_package_output_dirs(
        project, project_ts_configs, Path(project.root_dir)
    )

    process = await _prepare_tsc_build_process(
        project,
        subsystem,
        input_digest,
        package_output_dirs,
        project_targets,
        build_root,
    )

    process = replace(process, cache_scope=check_subsystem.default_process_cache_scope)

    result = await execute_process(process, **implicitly())

    return CheckResult.from_fallible_process_result(
        result,
        partition_description=f"TypeScript check on {project.root_dir} ({len(project_targets)} targets)",
        output_simplifier=global_options.output_simplifier(),
    )


@rule(desc="Check TypeScript compilation")
async def typecheck_typescript(
    request: TypeScriptCheckRequest,
    subsystem: TypeScriptSubsystem,
    check_subsystem: CheckSubsystem,
    global_options: GlobalOptions,
    build_root: BuildRoot,
) -> CheckResults:
    if subsystem.skip:
        return CheckResults([], checker_name=request.tool_name, output_per_partition=False)

    field_sets = request.field_sets
    (
        all_projects,
        all_targets,
        all_package_jsons,
        all_ts_configs,
        owning_packages,
    ) = await concurrently(
        find_node_js_projects(**implicitly()),
        find_all_targets(),
        all_package_json(),
        construct_effective_ts_configs(),
        concurrently(
            find_owning_package(OwningNodePackageRequest(field_set.address), **implicitly())
            for field_set in field_sets
        ),
    )

    projects: OrderedSet[NodeJSProject] = OrderedSet()
    for owning_package in owning_packages:
        if owning_package.target:
            package_directory = owning_package.target.address.spec_path
            owning_project = all_projects.project_for_directory(package_directory)
            if owning_project:
                projects.add(owning_project)

    project_results = await concurrently(
        _typecheck_single_project(
            project,
            subsystem,
            check_subsystem,
            global_options,
            all_targets,
            all_projects,
            all_package_jsons,
            all_ts_configs,
            build_root,
        )
        for project in projects
    )

    return CheckResults(project_results, checker_name=request.tool_name, output_per_partition=False)


def rules():
    return [
        *collect_rules(),
        UnionRule(CheckRequest, TypeScriptCheckRequest),
    ]
