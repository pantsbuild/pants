# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
import os

from pants.backend.adhoc.target_types import (
    AdhocToolArgumentsField,
    AdhocToolExecutionDependenciesField,
    AdhocToolExtraEnvVarsField,
    AdhocToolLogOutputField,
    AdhocToolNamedCachesField,
    AdhocToolOutputDirectoriesField,
    AdhocToolOutputFilesField,
    AdhocToolOutputRootDirField,
    AdhocToolRunnableDependenciesField,
    AdhocToolRunnableField,
    AdhocToolSourcesField,
    AdhocToolStderrFilenameField,
    AdhocToolStdoutFilenameField,
    AdhocToolWorkdirField,
    AdhocToolWorkspaceInvalidationSourcesField,
)
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.core.target_types import FileSourceField
from pants.core.util_rules.adhoc_process_support import (
    AdhocProcessRequest,
    AdhocProcessResult,
    ToolRunner,
    ToolRunnerRequest,
)
from pants.core.util_rules.adhoc_process_support import rules as adhoc_process_support_rules
from pants.core.util_rules.environments import EnvironmentNameRequest, EnvironmentTarget
from pants.engine.environment import EnvironmentName
from pants.engine.fs import Digest, PathGlobs, Snapshot
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import GeneratedSources, GenerateSourcesRequest
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class GenerateFilesFromAdhocToolRequest(GenerateSourcesRequest):
    input = AdhocToolSourcesField
    output = FileSourceField


@rule(desc="Running run_in_sandbox target", level=LogLevel.DEBUG)
async def run_in_sandbox_request(
    request: GenerateFilesFromAdhocToolRequest,
    env_target: EnvironmentTarget,
) -> GeneratedSources:
    target = request.protocol_target
    description = f"the `{target.alias}` at {target.address}"

    environment_name = await Get(
        EnvironmentName, EnvironmentNameRequest, EnvironmentNameRequest.from_target(target)
    )

    runnable_address_str = target[AdhocToolRunnableField].value
    if not runnable_address_str:
        raise Exception(f"Must supply a value for `runnable` for {description}.")

    tool_runner = await Get(
        ToolRunner,
        ToolRunnerRequest(
            runnable_address_str=runnable_address_str,
            args=target.get(AdhocToolArgumentsField).value or (),
            execution_dependencies=target.get(AdhocToolExecutionDependenciesField).value or (),
            runnable_dependencies=target.get(AdhocToolRunnableDependenciesField).value or (),
            target=request.protocol_target,
            named_caches=FrozenDict(target.get(AdhocToolNamedCachesField).value or {}),
        ),
    )

    working_directory = target[AdhocToolWorkdirField].value or ""
    root_output_directory = target[AdhocToolOutputRootDirField].value or ""

    output_files = target.get(AdhocToolOutputFilesField).value or ()
    output_directories = target.get(AdhocToolOutputDirectoriesField).value or ()

    cache_scope = env_target.default_cache_scope

    workspace_invalidation_globs: PathGlobs | None = None
    workspace_invalidation_sources = (
        target.get(AdhocToolWorkspaceInvalidationSourcesField).value or ()
    )
    if workspace_invalidation_sources:
        spec_path = target.address.spec_path
        workspace_invalidation_globs = PathGlobs(
            globs=(os.path.join(spec_path, glob) for glob in workspace_invalidation_sources),
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin=f"`{AdhocToolWorkspaceInvalidationSourcesField.alias}` for `adhoc_tool` target at `{target.address}`",
        )

    process_request = AdhocProcessRequest(
        description=description,
        address=target.address,
        working_directory=working_directory,
        root_output_directory=root_output_directory,
        argv=tool_runner.args,
        timeout=None,
        input_digest=tool_runner.digest,
        immutable_input_digests=FrozenDict.frozen(tool_runner.immutable_input_digests),
        append_only_caches=FrozenDict(tool_runner.append_only_caches),
        output_files=output_files,
        output_directories=output_directories,
        fetch_env_vars=target.get(AdhocToolExtraEnvVarsField).value or (),
        supplied_env_var_values=FrozenDict(tool_runner.extra_env),
        log_on_process_errors=None,
        log_output=target[AdhocToolLogOutputField].value,
        capture_stderr_file=target[AdhocToolStderrFilenameField].value,
        capture_stdout_file=target[AdhocToolStdoutFilenameField].value,
        workspace_invalidation_globs=workspace_invalidation_globs,
        cache_scope=cache_scope,
    )

    adhoc_result = await Get(
        AdhocProcessResult,
        {
            environment_name: EnvironmentName,
            process_request: AdhocProcessRequest,
        },
    )

    output = await Get(Snapshot, Digest, adhoc_result.adjusted_digest)
    return GeneratedSources(output)


def rules():
    return [
        *collect_rules(),
        *adhoc_process_support_rules(),
        UnionRule(GenerateSourcesRequest, GenerateFilesFromAdhocToolRequest),
    ]
