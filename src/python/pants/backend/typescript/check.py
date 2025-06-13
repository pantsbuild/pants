# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from pants.backend.javascript.subsystems.nodejs_tool import NodeJSToolRequest
from pants.backend.typescript.subsystem import TypeScriptSubsystem
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
    
    # For workspace compilation, we need ALL TypeScript sources in the workspace,
    # not just the sources from the targets being checked, because TypeScript needs
    # to resolve workspace dependencies like @pants-example/common-types
    all_workspace_sources = await path_globs_to_digest(
        PathGlobs([
            "src/python/pants/backend/typescript/examples/**/src/**/*.ts",
            "src/python/pants/backend/typescript/examples/**/src/**/*.tsx",
        ]),
        **implicitly()
    )
    
    # DEBUG: Log what source files were captured
    source_contents = await Get(DigestContents, Digest, all_workspace_sources)
    logger.info(f"DEBUG: Captured {len(source_contents)} source files:")
    for file_content in sorted(source_contents, key=lambda f: f.path):
        logger.info(f"DEBUG:   {file_content.path}")
    
    # Get source files for the specific field sets being checked (for validation)
    target_sources = await concurrently(
        hydrate_sources(HydrateSourcesRequest(field_set.sources), **implicitly())
        for field_set in field_sets
    )
    
    # Collect source files for validation
    all_source_files = []
    for sources in target_sources:
        all_source_files.extend(sources.snapshot.files)
    
    if not all_source_files:
        return CheckResults([], checker_name=tool_name)
    
    # Include TypeScript configuration files AND package.json files for each workspace package
    config_files = [
        # Root workspace files
        "src/python/pants/backend/typescript/examples/tsconfig.json",
        "src/python/pants/backend/typescript/examples/package.json",
        "src/python/pants/backend/typescript/examples/pnpm-workspace.yaml",
        "src/python/pants/backend/typescript/examples/.npmrc",
        # Each workspace package needs both tsconfig.json and package.json
        "src/python/pants/backend/typescript/examples/common-types/tsconfig.json",
        "src/python/pants/backend/typescript/examples/common-types/package.json", 
        "src/python/pants/backend/typescript/examples/shared-utils/tsconfig.json",
        "src/python/pants/backend/typescript/examples/shared-utils/package.json",
        "src/python/pants/backend/typescript/examples/shared-components/tsconfig.json",
        "src/python/pants/backend/typescript/examples/shared-components/package.json",
        "src/python/pants/backend/typescript/examples/main-app/tsconfig.json",
        "src/python/pants/backend/typescript/examples/main-app/package.json",
    ]
    
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
    
    # Use the TypeScript subsystem's tool request with resolve-based installation
    # The resolve system will automatically handle package installation and working directory
    tool_request = subsystem.request(
        args=args,
        input_digest=input_digest,
        description=f"Type-check TypeScript monorepo ({len(field_sets)} targets)",
        level=LogLevel.DEBUG,
    )
    
    # Execute TypeScript type checking - resolve system handles environment setup
    process = await Get(Process, NodeJSToolRequest, tool_request)
    
    # Set the working directory to the examples root where tsconfig.json is located
    process_with_workdir = replace(process, working_directory="src/python/pants/backend/typescript/examples")
    
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
