# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass

from pants.backend.javascript import install_node_package
from pants.backend.javascript.install_node_package import (
    InstalledNodePackageRequest,
    install_node_packages_for_address,
)
from pants.backend.javascript.subsystems.nodejs_tool import NodeJSToolRequest
from pants.backend.typescript.subsystem import TypeScriptSubsystem
from pants.backend.typescript.target_types import (
    TypeScriptSourceField,
    TypeScriptSourceTarget,
    TypeScriptTestSourceField,
)
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.engine.fs import PathGlobs
from pants.engine.internals.graph import hydrate_sources, HydrateSourcesRequest
from pants.engine.internals.native_engine import Address, MergeDigests
from pants.engine.internals.selectors import Get, concurrently
from pants.engine.intrinsics import execute_process, path_globs_to_digest, merge_digests
from pants.engine.process import Process
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import BoolField, FieldSet, Target
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
    
    # Get source files for all field sets
    all_sources = await concurrently(
        hydrate_sources(HydrateSourcesRequest(field_set.sources), **implicitly())
        for field_set in field_sets
    )
    
    # For Phase 1: Install all workspace packages to ensure all dependencies are available
    # Get unique addresses to avoid duplicate installations
    unique_addresses = {field_set.address for field_set in field_sets}
    # Also include the workspace root to get workspace-level dependencies
    unique_addresses.add(Address("src/python/pants/backend/typescript/examples"))
    
    installations = await concurrently(
        install_node_packages_for_address(InstalledNodePackageRequest(address), **implicitly())
        for address in unique_addresses
    )
    
    # Merge all installation digests to include all workspace packages and their dependencies
    installation_digests = [installation.digest for installation in installations]
    merged_installation_digest = await merge_digests(MergeDigests(installation_digests))
    
    # Phase 1: Compile all packages together to handle project references properly
    # Collect all source files from all field sets
    all_source_files = []
    for sources in all_sources:
        all_source_files.extend(sources.snapshot.files)
    
    if not all_source_files:
        return CheckResults([], checker_name=tool_name)
    
    # For --build to work with project references, include ALL TypeScript source files in the monorepo
    # This ensures referenced projects have their source files available
    all_ts_sources_digest = await path_globs_to_digest(
        PathGlobs([
            "**/src/**/*.ts",
            "**/src/**/*.tsx", 
            "**/src/**/*.js",
            "**/src/**/*.jsx",
            "**/tsconfig*.json", 
            "**/jsconfig*.json",
            "**/package.json",
            "**/pnpm-workspace.yaml",
            "**/yarn.lock",
            "**/package-lock.json", 
            "**/pnpm-lock.yaml",
        ]),
        **implicitly()
    )
    
    # Merge all installations and all source files
    input_digest = await merge_digests(
        MergeDigests((merged_installation_digest, all_ts_sources_digest))
    )
    
    # Set working directory to the examples directory where the monorepo is located
    examples_dir = "src/python/pants/backend/typescript/examples"
    
    # Use --build without specific project path to build all projects in workspace
    args = ("--build",)
    
    
    # Use the TypeScript subsystem's tool request for proper environment setup
    # This avoids the package filtering that comes with NodeJsProjectEnvironmentProcess
    tool_request = subsystem.request(
        args=args,
        input_digest=input_digest,
        description=f"Type-check TypeScript monorepo ({len(field_sets)} targets)",
        level=LogLevel.DEBUG,
    )
    
    # Execute TypeScript type checking with correct working directory
    process = await Get(Process, NodeJSToolRequest, tool_request)
    process = dataclasses.replace(
        process, 
        working_directory=examples_dir,
        # Add system utilities to fix uname issue
        env={**process.env, "PATH": f"{process.env.get('PATH', '')}:/usr/bin:/bin:/usr/sbin:/sbin"}
    )
    
    result = await execute_process(process, **implicitly())
    
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
        *install_node_package.rules(),
        UnionRule(CheckRequest, TypeScriptCheckRequest),
        # UnionRule(CheckRequest, TypeScriptTestCheckRequest),
        TypeScriptSourceTarget.register_plugin_field(SkipTypeScriptCheckField),
        # TypeScriptTestTarget.register_plugin_field(SkipTypeScriptCheckField),
    ]
