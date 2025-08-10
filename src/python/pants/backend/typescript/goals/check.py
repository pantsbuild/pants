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
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.core.target_types import FileSourceField
from pants.core.util_rules.system_binaries import CpBinary, MkdirBinary, MktempBinary, MvBinary
from pants.engine.collection import Collection
from pants.engine.fs import (
    EMPTY_DIGEST,
    CreateDigest,
    Digest,
    DigestSubset,
    FileContent,
    GlobMatchErrorBehavior,
    PathGlobs,
)
from pants.engine.internals.graph import find_all_targets, hydrate_sources, transitive_targets
from pants.engine.internals.native_engine import MergeDigests
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import (
    create_digest,
    digest_subset_to_digest,
    digest_to_snapshot,
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
from pants.option.global_options import GlobalOptions, NamedCachesDirOption
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

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
        cfg for cfg in all_ts_configs if os.path.basename(cfg.path) == "tsconfig.json"
    ]

    for ts_config in tsconfig_json_files:
        config_dir = os.path.normpath(os.path.dirname(ts_config.path))

        if config_dir in workspace_dir_map:
            workspace_dir_to_tsconfig[config_dir] = ts_config

    return workspace_dir_to_tsconfig


def _calculate_resolved_output_dirs(
    project: NodeJSProject, all_ts_configs, project_root_path: Path
) -> set[str]:
    workspace_dir_to_tsconfig = _build_workspace_tsconfig_map(project.workspaces, all_ts_configs)

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
        transitive_targets_result = await transitive_targets(
            TransitiveTargetsRequest(typescript_addresses), **implicitly()
        )

        for target in transitive_targets_result.closure:
            if target.has_field(FileSourceField):
                file_path = target[FileSourceField].file_path
                if file_path.startswith(project.root_dir):
                    config_files.append(file_path)

    return config_files


# TODO: use set -e if we go ahead with this approach
async def _create_typescript_cache_wrapper_script(
    project: NodeJSProject,
    cp_binary: CpBinary,
    mkdir_binary: MkdirBinary,
    mktemp_binary: MktempBinary,
    mv_binary: MvBinary,
    resolved_output_dirs: set[str],
    build_root: BuildRoot,
    named_caches_dir: NamedCachesDirOption,
) -> Digest:
    """Create shell script wrapper for TypeScript incremental compilation caching.

    Returns:
        Script digest for merging with input digest
    """
    # Generate cache key based on both build_root and project path
    # This ensures cache isolation between different test runs/build_roots
    project_relative_path = os.path.relpath(project.root_dir, build_root.path)
    cache_input = f"{build_root.path}:{project_relative_path}"
    cache_key = sha256(cache_input.encode()).hexdigest()

    # Use conditional cache path strategy (following PEX pattern)
    # When named_caches_dir is set (integration tests), use absolute host paths
    # Otherwise, rely on engine symlinks via mounted cache directories
    if named_caches_dir.val:
        # Integration test mode: use absolute host cache directory path
        # Normalize path to handle macOS /tmp -> /private/tmp symlink issue
        cache_base_dir = str(named_caches_dir.val)
        if cache_base_dir.startswith("/private/tmp/"):
            cache_base_dir = cache_base_dir[8:]  # Remove "/private" prefix
        host_cache_dir = os.path.join(cache_base_dir, "typescript_cache")
        project_cache_subdir = os.path.join(host_cache_dir, cache_key)
        use_host_paths = True
    else:
        # Normal mode: use engine-provided mounted cache (relative paths)
        host_cache_dir = "typescript_cache"  # Mounted by append_only_caches
        project_cache_subdir = f"typescript_cache/{cache_key}"
        use_host_paths = False

    # Build workspace directories list from project workspaces
    workspace_dirs = []
    for workspace_pkg in project.workspaces:
        if workspace_pkg.root_dir != project.root_dir:
            # Get relative path from project root to workspace package
            workspace_relative = workspace_pkg.root_dir.removeprefix(f"{project.root_dir}/")
            workspace_dirs.append(workspace_relative)
        else:
            # Main project workspace
            workspace_dirs.append(".")

    # Convert to shell array format
    workspace_dirs_str = " ".join(f'"{d}"' for d in workspace_dirs)
    output_dirs_str = " ".join(f'"{d}"' for d in resolved_output_dirs)

    # Create shell script wrapper following MyPy atomic cache pattern
    from textwrap import dedent

    script_content = dedent(f'''\
        #!/bin/sh
        # TypeScript incremental compilation cache wrapper
        # Following MyPy pattern - atomic directory operations, paths provided by Python
        set -e

        # Arguments: cp_binary mkdir_binary mktemp_binary mv_binary [tsc_command...]
        CP_BIN="$1"
        MKDIR_BIN="$2"
        MKTEMP_BIN="$3"
        MV_BIN="$4"
        shift 4

        # Cache paths injected from Python - conditional strategy
        # Use absolute host paths for integration tests, relative paths for normal runs
        PERSISTENT_CACHE_DIR="{host_cache_dir}"
        CACHE_KEY="{cache_key}"
        PROJECT_CACHE_SUBDIR="{project_cache_subdir}"
        PROJECT_ROOT="{project.root_dir}"
        USE_HOST_PATHS="{use_host_paths}"
        NAMED_CACHES_DIR_VAL="{named_caches_dir.val if named_caches_dir.val else "NOT_SET"}"
        
        # Debug: Show environment and current working directory
        echo "DEBUG: Current working directory: $(pwd)"
        echo "DEBUG: PROJECT_CACHE_SUBDIR=$PROJECT_CACHE_SUBDIR"  
        echo "DEBUG: PERSISTENT_CACHE_DIR=$PERSISTENT_CACHE_DIR"  
        echo "DEBUG: Contents of current directory: $(echo *)"
        echo "DEBUG: USE_HOST_PATHS=$USE_HOST_PATHS"
        echo "DEBUG: NAMED_CACHES_DIR_VAL=$NAMED_CACHES_DIR_VAL"
        echo "DEBUG: RUN_NUMBER=$RUN_NUMBER"

        if [ "$USE_HOST_PATHS" = "True" ]; then
            echo "DEBUG: Using absolute host cache paths (integration test mode)"
            echo "DEBUG: Host cache directory exists: $([ -d \"$PERSISTENT_CACHE_DIR\" ] && echo 'YES' || echo 'NO')"
        else
            echo "DEBUG: Using engine-mounted cache paths (normal mode)"
            echo "DEBUG: Mounted cache directory exists: $([ -d \"$PERSISTENT_CACHE_DIR\" ] && echo 'YES' || echo 'NO')"
        fi

        if [ -d "$PERSISTENT_CACHE_DIR" ]; then
            echo "DEBUG: Contents of cache directory: $(ls \"$PERSISTENT_CACHE_DIR\"/ 2>/dev/null || echo 'EMPTY')"
        else
            echo "DEBUG: Cache directory does NOT exist at $PERSISTENT_CACHE_DIR"
            # Check if cache exists at alternative path (macOS symlink issue)
            ALT_PATH="${{PERSISTENT_CACHE_DIR#/private}}"
            if [ "$ALT_PATH" != "$PERSISTENT_CACHE_DIR" ] && [ -d "$ALT_PATH" ]; then
                echo "DEBUG: Cache found at alternative path: $ALT_PATH"
                echo "DEBUG: Alternative path contents: $(ls \"$ALT_PATH\"/ 2>/dev/null || echo 'EMPTY')"
            fi
        fi

        # Step 1: Restore cache from persistent storage to project root
        # This puts output directories and .tsbuildinfo files where tsc expects them
        echo "DEBUG: Checking project cache subdirectory existence before restoration..."
        echo "DEBUG: PROJECT_CACHE_SUBDIR=$PROJECT_CACHE_SUBDIR"
        echo "DEBUG: Project cache subdir exists: $([ -d \"$PROJECT_CACHE_SUBDIR\" ] && echo 'YES' || echo 'NO')" 

        # Check for cache at primary path or alternative path (handle macOS symlink issue)
        CACHE_FOUND_PATH=""
        if [ -d "$PROJECT_CACHE_SUBDIR" ]; then
            CACHE_FOUND_PATH="$PROJECT_CACHE_SUBDIR"
        else
            # Try alternative path without /private prefix
            ALT_PROJECT_CACHE="${{PROJECT_CACHE_SUBDIR#/private}}"
            echo "DEBUG: Trying alternative path: $ALT_PROJECT_CACHE"
            echo "DEBUG: Original path: $PROJECT_CACHE_SUBDIR"
            echo "DEBUG: Alternative path exists: $([ -d \"$ALT_PROJECT_CACHE\" ] && echo 'YES' || echo 'NO')"
            if [ "$ALT_PROJECT_CACHE" != "$PROJECT_CACHE_SUBDIR" ] && [ -d "$ALT_PROJECT_CACHE" ]; then
                echo "DEBUG: Cache found at alternative path: $ALT_PROJECT_CACHE"
                CACHE_FOUND_PATH="$ALT_PROJECT_CACHE"
            fi
        fi

        if [ -n "$CACHE_FOUND_PATH" ]; then
            echo "Restoring cache from $CACHE_FOUND_PATH"

            echo "DEBUG: Paths and accessibility:"
            echo "DEBUG: PWD=$(pwd)"
            echo "DEBUG: PERSISTENT_CACHE_DIR=$PERSISTENT_CACHE_DIR"
            echo "DEBUG: PROJECT_ROOT=$PROJECT_ROOT"
            echo "DEBUG: Cache dir exists: $([ -d "$PERSISTENT_CACHE_DIR" ] && echo 'YES' || echo 'NO')"
            echo "DEBUG: Project dir exists: YES (current directory)"

            echo "DEBUG: Cache key: $CACHE_KEY"
            echo "DEBUG: Project cache subdirectory contents:"
            echo "Contents: $(echo "$PROJECT_CACHE_SUBDIR"/*)"

            echo "DEBUG: Project directory before copy:"
            echo "Contents: $(echo *)"

            # TEST: Touch cache files before copying to make them newer than sources
            # But also touch index.ts to trigger TypeScript's metadata validation
            echo "DEBUG: Touching cache files to make them newer than source files"
            # Use shell globbing instead of find - touch all files recursively
            for cache_file in "$PROJECT_CACHE_SUBDIR"/*; do
                if [ -f "$cache_file" ]; then
                    touch "$cache_file"
                fi
            done
            # Also touch files in subdirectories
            for cache_subdir in "$PROJECT_CACHE_SUBDIR"/*; do
                if [ -d "$cache_subdir" ]; then
                    for cache_file in "$cache_subdir"/*; do
                        if [ -f "$cache_file" ]; then
                            touch "$cache_file"
                        fi
                    done
                fi
            done

            echo "DEBUG: Executing copy command from project cache subdirectory:"
            if "$CP_BIN" -a "$PROJECT_CACHE_SUBDIR/." .; then
                echo "DEBUG: Copy command succeeded"
            else
                echo "ERROR: Copy command failed with exit code $?"
                exit 1
            fi

            echo "DEBUG: Project directory after copy:"
            echo "Contents: $(echo *)"
            echo "Checking for specific files:"
            echo "common-types/tsconfig.tsbuildinfo: $([ -f "common-types/tsconfig.tsbuildinfo" ] && echo 'EXISTS' || echo 'MISSING')"
            echo "dist/tsconfig.tsbuildinfo: $([ -f "dist/tsconfig.tsbuildinfo" ] && echo 'EXISTS' || echo 'MISSING')"

            # TEST: Touch all index.ts files to trigger selective TypeScript validation
            # Cache files are newer (bypass mtime fast-path) but specific source files are newest
            # This should trigger TypeScript to recheck only the modified files
            # TODO: can we touch all .ts or .js files ? What's the right approach here?
            echo "DEBUG: Touching all index.ts files to trigger selective validation"

            # Touch all index.ts files in the project using shell globbing
            # Check root directory
            if [ -f "index.ts" ]; then
                touch "index.ts"
                echo "DEBUG: Touched ./index.ts"
            fi
            # Check subdirectories and src subdirectories for index.ts files
            for dir in */; do
                if [ -d "$dir" ]; then
                    if [ -f "$dir/index.ts" ]; then
                        touch "$dir/index.ts"
                        echo "DEBUG: Touched $dir/index.ts"
                    fi
                    if [ -f "$dir/src/index.ts" ]; then
                        touch "$dir/src/index.ts"
                        echo "DEBUG: Touched $dir/src/index.ts"
                    fi
                fi
            done

            echo "DEBUG: Cache restoration complete, timestamp management applied"

            echo "Cache restored successfully"
        else
            echo "No cached build found - performing full build"
        fi

        # Step 2: Run TypeScript compiler (already in project root due to working_directory)
        "$@"

        # If TypeScript failed, exit immediately - no cache operations needed
        if [ $? -ne 0 ]; then
            echo "TypeScript compilation failed - exiting"
            exit $?
        fi

        # TypeScript succeeded - proceed with file touching and cache operations
        echo "DEBUG: Touching .tsbuildinfo files to ensure they are captured in output digest"
        for workspace_dir in {workspace_dirs_str}; do
            tsbuildinfo_file="$workspace_dir/tsconfig.tsbuildinfo"
            if [ -f "$tsbuildinfo_file" ]; then
                touch "$tsbuildinfo_file"
                echo "DEBUG: Touched $tsbuildinfo_file for output capture"
            else
                echo "DEBUG: No $tsbuildinfo_file found to touch"
            fi
        done

        # Step 3: Save cache contents directly from project (compilation succeeded)
        echo "Saving compilation cache"

            # Create temp dir in persistent cache filesystem for atomic operation
            CACHE_PARENT="${{PROJECT_CACHE_SUBDIR%/*}}"
            CACHE_BASENAME="${{PROJECT_CACHE_SUBDIR##*/}}"

            # Ensure parent directory exists before creating temp dir
            "$MKDIR_BIN" -p "$CACHE_PARENT"

            TMP_PERSISTENT_DIR="$("$MKTEMP_BIN" -d "$CACHE_PARENT/${{CACHE_BASENAME}}.tmp.XXXXXX")"
            echo "DEBUG: Created temp cache directory $TMP_PERSISTENT_DIR"

            # Copy .tsbuildinfo files from workspace packages directly to cache
            for workspace_dir in {workspace_dirs_str}; do
                tsbuildinfo_file="$workspace_dir/tsconfig.tsbuildinfo"
                if [ -f "$tsbuildinfo_file" ]; then
                    echo "DEBUG: Found $workspace_dir/tsconfig.tsbuildinfo, saving to cache"
                    "$MKDIR_BIN" -p "$TMP_PERSISTENT_DIR/$workspace_dir"
                    "$CP_BIN" "$tsbuildinfo_file" "$TMP_PERSISTENT_DIR/$workspace_dir/" || echo "DEBUG: Failed to copy $workspace_dir/tsconfig.tsbuildinfo"
                else
                    echo "DEBUG: No tsconfig.tsbuildinfo found in $workspace_dir"
                fi
            done

            # Copy output directories directly to cache
            for output_dir in {output_dirs_str}; do
                if [ -d "$output_dir" ]; then
                    echo "DEBUG: Found $output_dir directory, saving to cache"
                    output_parent="$(dirname "$output_dir")"
                    "$MKDIR_BIN" -p "$TMP_PERSISTENT_DIR/$output_parent"
                    "$CP_BIN" -r "$output_dir" "$TMP_PERSISTENT_DIR/$output_parent/" || echo "DEBUG: Failed to copy $output_dir"
                else
                    echo "DEBUG: No $output_dir directory found"
                fi
            done

            # Atomic replace: backup old -> move new -> remove backup
            OLD_BACKUP="$PROJECT_CACHE_SUBDIR.bak.$$"
            "$MV_BIN" "$PROJECT_CACHE_SUBDIR" "$OLD_BACKUP" 2>/dev/null || echo "DEBUG: No existing cache to backup"
            "$MV_BIN" "$TMP_PERSISTENT_DIR" "$PROJECT_CACHE_SUBDIR"
            MV_EXIT_CODE=$?
            if [ $MV_EXIT_CODE -eq 0 ]; then
                echo "DEBUG: Atomically moved temp to project cache subdirectory successfully"
            else
                echo "ERROR: Failed to move temp cache to project cache location, exit code: $MV_EXIT_CODE"
                echo "ERROR: Source: $TMP_PERSISTENT_DIR"
                echo "ERROR: Target: $PROJECT_CACHE_SUBDIR"
            fi
            rm -rf "$OLD_BACKUP" 2>/dev/null || true

            # Verify cache was actually saved
            if [ -d "$PROJECT_CACHE_SUBDIR" ]; then
                echo "Cache updated successfully - verified at $PROJECT_CACHE_SUBDIR"
            else
                echo "ERROR: Cache directory does not exist after save attempt!"
            fi
    ''')

    # Create script digest in project directory (since we run from project.root_dir)
    script_digest = await create_digest(
        CreateDigest(
            [
                FileContent(
                    f"{project.root_dir}/__typescript_cache_wrapper.sh",
                    script_content.encode(),
                    is_executable=True,
                )
            ]
        ),
        **implicitly(),
    )

    return script_digest


@dataclass(frozen=True)
class TypeScriptCheckFieldSet(FieldSet):
    required_fields = (JSRuntimeSourceField,)

    sources: JSRuntimeSourceField


class TypeScriptCheckRequest(CheckRequest):
    field_set_type = TypeScriptCheckFieldSet
    tool_name = TypeScriptSubsystem.options_scope


async def _typecheck_typescript_projects(
    field_sets: Collection[TypeScriptCheckFieldSet],
    subsystem: TypeScriptSubsystem,
    global_options: GlobalOptions,
    build_root: BuildRoot,
    cp_binary: CpBinary,
    mkdir_binary: MkdirBinary,
    mktemp_binary: MktempBinary,
    mv_binary: MvBinary,
    named_caches_dir: NamedCachesDirOption,
) -> tuple[CheckResult, ...]:
    """Type check TypeScript projects, grouping targets by their containing NodeJS project."""
    if not field_sets:
        return ()

    all_projects, all_targets, all_package_jsons, all_ts_configs = await concurrently(
        find_node_js_projects(**implicitly()),
        find_all_targets(),
        all_package_json(),
        construct_effective_ts_configs(),
    )

    owning_packages = await concurrently(
        find_owning_package(OwningNodePackageRequest(field_set.address), **implicitly())
        for field_set in field_sets
    )

    projects_to_field_sets: dict[NodeJSProject, list[TypeScriptCheckFieldSet]] = {}
    for field_set, owning_package in zip(field_sets, owning_packages):
        if owning_package.target:
            package_directory = owning_package.target.address.spec_path
            owning_project = all_projects.project_for_directory(package_directory)
            if owning_project:
                if owning_project not in projects_to_field_sets:
                    projects_to_field_sets[owning_project] = []
                projects_to_field_sets[owning_project].append(field_set)

    project_results = await concurrently(
        _typecheck_single_project(
            project,
            subsystem,
            global_options,
            all_targets,
            all_projects,
            all_package_jsons,
            all_ts_configs,
            build_root,
            cp_binary,
            mkdir_binary,
            mktemp_binary,
            mv_binary,
            named_caches_dir,
        )
        for project in projects_to_field_sets.keys()
    )

    return project_results


async def _find_project_typescript_targets(
    project: NodeJSProject,
    all_targets: AllTargets,
    all_projects: AllNodeJSProjects,
) -> list[Target] | None:
    """Find all TypeScript targets belonging to the specified project.

    Returns None if no TypeScript targets found in the project. TypeScript compilation needs all
    sources in a project to resolve imports correctly.
    """
    # Find ALL TypeScript targets in workspace
    typescript_targets = [
        target
        for target in all_targets
        if (target.has_field(TypeScriptSourceField) or target.has_field(TypeScriptTestSourceField))
    ]

    # Get owning packages for all TypeScript targets to filter to this project
    typescript_owning_packages = await concurrently(
        find_owning_package(OwningNodePackageRequest(target.address), **implicitly())
        for target in typescript_targets
    )

    # Filter to targets that belong to the current project
    project_typescript_targets = []
    for target, owning_package in zip(typescript_targets, typescript_owning_packages):
        if owning_package.target:
            package_directory = owning_package.target.address.spec_path
            target_project = all_projects.project_for_directory(package_directory)
            if target_project == project:
                project_typescript_targets.append(target)

    return project_typescript_targets if project_typescript_targets else None


async def _hydrate_project_sources(
    project_typescript_targets: list[Target],
) -> Digest:
    """Hydrate and merge all source files for TypeScript targets in the project."""
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

    all_workspace_digests = [sources.snapshot.digest for sources in workspace_target_sources]
    return await merge_digests(MergeDigests(all_workspace_digests))


async def _prepare_compilation_input(
    project: NodeJSProject,
    project_typescript_targets: list[Target],
    all_package_jsons: AllPackageJson,
    all_ts_configs: AllTSConfigs,
    all_workspace_sources: Digest,
) -> Digest:
    """Prepare input digest for TypeScript compilation.

    Returns the input digest containing sources and configuration files.
    """
    # Collect all config files needed for TypeScript compilation
    config_files = await _collect_config_files_for_project(
        project, project_typescript_targets, all_package_jsons, all_ts_configs
    )

    # Keep the original tsconfig.json files in config_files since we're not modifying them

    # Validate that all TypeScript configurations have explicit outDir settings
    project_ts_configs = [
        config for config in all_ts_configs if config.path.startswith(project.root_dir)
    ]
    for ts_config in project_ts_configs:
        ts_config.validate_outdir()

    # Get config file digests (including main tsconfig.json)
    config_digest = (
        await path_globs_to_digest(
            PathGlobs(config_files, glob_match_error_behavior=GlobMatchErrorBehavior.ignore),
            **implicitly(),
        )
        if config_files
        else EMPTY_DIGEST
    )

    # Merge workspace sources and config files
    all_digests = [all_workspace_sources] + (
        [config_digest] if config_digest != EMPTY_DIGEST else []
    )
    input_digest = await merge_digests(MergeDigests(all_digests))

    return input_digest


async def _prepare_typescript_tool_process(
    project: NodeJSProject,
    subsystem: TypeScriptSubsystem,
    input_digest: Digest,
    resolved_output_dirs: set[str],
    project_typescript_targets: list[Target],
    cp_binary: CpBinary,
    mkdir_binary: MkdirBinary,
    mktemp_binary: MktempBinary,
    mv_binary: MvBinary,
    build_root: BuildRoot,
    named_caches_dir: NamedCachesDirOption,
) -> Process:
    """Prepare the TypeScript compiler process for execution with shell script wrapper for
    caching."""
    # Determine which resolve to use for this TypeScript project
    project_address = Address(project.root_dir)
    project_resolve = await resolve_for_package(RequestNodeResolve(project_address), **implicitly())

    # Use named cache for TypeScript incremental compilation following MyPy pattern
    named_cache_key = "typescript_cache"
    named_cache_dir = "typescript_cache"  # Use cache key as directory like MyPy

    # Create shell script wrapper for cache management
    script_digest = await _create_typescript_cache_wrapper_script(
        project,
        cp_binary,
        mkdir_binary,
        mktemp_binary,
        mv_binary,
        resolved_output_dirs,
        build_root,
        named_caches_dir,
    )

    # Merge script with input digest
    merged_input = await merge_digests(MergeDigests([input_digest, script_digest]))

    # Create TypeScript args using --build command
    # Note: --tsBuildInfoFile will be added by the shell script wrapper
    tsc_args = ("--build", *subsystem.extra_build_args)

    typescript_append_only_caches = FrozenDict({named_cache_key: named_cache_dir})

    # Debug: Log cache configuration
    logger = logging.getLogger(__name__)
    logger.debug(f"TypeScript cache configuration: {typescript_append_only_caches}")

    tool_request = subsystem.request(
        args=tsc_args,
        input_digest=merged_input,
        description=f"Type-check TypeScript project {project.root_dir} ({len(project_typescript_targets)} targets)",
        level=LogLevel.DEBUG,
        project_caches=typescript_append_only_caches,
    )

    # Debug: Log tool request cache fields
    logger.debug(f"Tool request project_caches: {tool_request.project_caches}")
    logger.debug(f"Tool request append_only_caches: {tool_request.append_only_caches}")

    # Override the resolve to use the project's resolve instead of default
    tool_request_with_resolve: NodeJSToolRequest = replace(
        tool_request, resolve=project_resolve.resolve_name
    )

    # Execute TypeScript type checking with the project's resolve
    process = await prepare_tool_process(tool_request_with_resolve, **implicitly())

    # TypeScript generates output directories in working directory
    output_directories = tuple(sorted(resolved_output_dirs))

    # Replace process to use shell script wrapper with system binaries as arguments
    # Set working_directory to project root so TypeScript runs where it expects and writes files there
    process_with_wrapper = replace(
        process,
        argv=(
            "./__typescript_cache_wrapper.sh",
            cp_binary.path,
            mkdir_binary.path,
            mktemp_binary.path,
            mv_binary.path,
        )
        + process.argv,
        working_directory=project.root_dir,
        output_directories=output_directories,
    )

    return process_with_wrapper


async def _typecheck_single_project(
    project: NodeJSProject,
    subsystem: TypeScriptSubsystem,
    global_options: GlobalOptions,
    all_targets: AllTargets,
    all_projects: AllNodeJSProjects,
    all_package_jsons: AllPackageJson,
    all_ts_configs: AllTSConfigs,
    build_root: BuildRoot,
    cp_binary: CpBinary,
    mkdir_binary: MkdirBinary,
    mktemp_binary: MktempBinary,
    mv_binary: MvBinary,
    named_caches_dir: NamedCachesDirOption,
) -> CheckResult:
    """Type check a single TypeScript project using all TypeScript targets in the project."""
    # Find all TypeScript targets for this project
    project_typescript_targets = await _find_project_typescript_targets(
        project, all_targets, all_projects
    )

    # Early return if no TypeScript targets in project
    if not project_typescript_targets:
        return CheckResult(
            exit_code=0,
            stdout="",
            stderr="",
            partition_description=f"TypeScript check on {project.root_dir} (no targets)",
        )

    # Hydrate all source files for the project
    all_workspace_sources = await _hydrate_project_sources(project_typescript_targets)

    # Prepare compilation input (sources and config files)
    input_digest = await _prepare_compilation_input(
        project,
        project_typescript_targets,
        all_package_jsons,
        all_ts_configs,
        all_workspace_sources,
    )

    # Calculate resolved output directories for process setup
    project_root_path = Path(project.root_dir)
    resolved_output_dirs = _calculate_resolved_output_dirs(
        project, all_ts_configs, project_root_path
    )

    # Prepare the TypeScript compiler process with shell script wrapper for caching
    process = await _prepare_typescript_tool_process(
        project,
        subsystem,
        input_digest,
        resolved_output_dirs,
        project_typescript_targets,
        cp_binary,
        mkdir_binary,
        mktemp_binary,
        mv_binary,
        build_root,
        named_caches_dir,
    )

    # Execute TypeScript compilation
    result = await execute_process(process, **implicitly())

    # Debug logging of output files
    logger = logging.getLogger(__name__)
    output_snapshot = await digest_to_snapshot(result.output_digest, **implicitly())
    logger.debug(f"TypeScript output files: {sorted(output_snapshot.files)}")
    logger.debug(f"TypeScript stdout: {result.stdout.decode()}")
    logger.debug(f"TypeScript stderr: {result.stderr.decode()}")

    # Extract user-facing outputs for the dist directory
    # This includes compiled .js, .d.ts files and other outputs users want to see
    artifact_globs = _get_typescript_artifact_globs(project, resolved_output_dirs)
    logger.debug(f"TypeScript artifact globs: {artifact_globs}")

    # Debug: Show what's actually in output digest
    output_snapshot = await digest_to_snapshot(result.output_digest, **implicitly())
    logger.debug(f"All output files: {sorted(output_snapshot.files)}")
    tsbuildinfo_in_output = [f for f in output_snapshot.files if f.endswith(".tsbuildinfo")]
    logger.debug(f"tsbuildinfo files in output: {tsbuildinfo_in_output}")

    user_outputs_digest = await digest_subset_to_digest(
        DigestSubset(
            result.output_digest,
            PathGlobs(artifact_globs, glob_match_error_behavior=GlobMatchErrorBehavior.ignore),
        ),
        **implicitly(),
    )

    # Debug: Show what was extracted as user outputs
    user_outputs_snapshot = await digest_to_snapshot(user_outputs_digest, **implicitly())
    logger.debug(f"User output files: {sorted(user_outputs_snapshot.files)}")
    tsbuildinfo_in_user_outputs = [
        f for f in user_outputs_snapshot.files if f.endswith(".tsbuildinfo")
    ]
    logger.debug(f"tsbuildinfo files in user outputs: {tsbuildinfo_in_user_outputs}")

    # Convert to CheckResult with user outputs in report field
    return CheckResult.from_fallible_process_result(
        result,
        partition_description=f"TypeScript check on {project.root_dir} ({len(project_typescript_targets)} targets)",
        report=user_outputs_digest,
        output_simplifier=global_options.output_simplifier(),
    )


@rule(desc="Check TypeScript compilation", level=LogLevel.DEBUG)
async def typecheck_typescript(
    request: TypeScriptCheckRequest,
    subsystem: TypeScriptSubsystem,
    global_options: GlobalOptions,
    build_root: BuildRoot,
    cp_binary: CpBinary,
    mkdir_binary: MkdirBinary,
    mktemp_binary: MktempBinary,
    mv_binary: MvBinary,
    named_caches_dir: NamedCachesDirOption,
) -> CheckResults:
    if subsystem.skip:
        return CheckResults([], checker_name=request.tool_name)

    check_results = await _typecheck_typescript_projects(
        request.field_sets,
        subsystem,
        global_options,
        build_root,
        cp_binary,
        mkdir_binary,
        mktemp_binary,
        mv_binary,
        named_caches_dir,
    )

    return CheckResults(check_results, checker_name=request.tool_name)


def rules():
    return [
        *collect_rules(),
        UnionRule(CheckRequest, TypeScriptCheckRequest),
    ]
