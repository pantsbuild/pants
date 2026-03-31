# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
import shlex
from dataclasses import dataclass

from pants.backend.shell.subsystems.shell_setup import ShellSetup
from pants.backend.shell.target_types import (
    RunShellCommandCommandField,
    RunShellCommandWorkdirField,
    ShellCommandCacheScopeField,
    ShellCommandCommandField,
    ShellCommandCommandFieldBase,
    ShellCommandExecutionDependenciesField,
    ShellCommandExtraEnvVarsField,
    ShellCommandLogOutputField,
    ShellCommandNamedCachesField,
    ShellCommandOutputDirectoriesField,
    ShellCommandOutputFilesField,
    ShellCommandOutputRootDirField,
    ShellCommandOutputsMatchMode,
    ShellCommandPathEnvModifyModeField,
    ShellCommandRunnableDependenciesField,
    ShellCommandSourcesField,
    ShellCommandTarget,
    ShellCommandTimeoutField,
    ShellCommandToolsField,
    ShellCommandWorkdirField,
    ShellCommandWorkspaceInvalidationSourcesField,
)
from pants.backend.shell.util_rules.builtin import BASH_BUILTIN_COMMANDS
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.core.environments.rules import EnvironmentNameRequest, resolve_environment_name
from pants.core.environments.target_types import EnvironmentTarget
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior, RunRequest
from pants.core.target_types import FileSourceField
from pants.core.util_rules.adhoc_process_support import (
    AdhocProcessRequest,
    ExtraSandboxContents,
    MergeExtraSandboxContents,
    ResolveExecutionDependenciesRequest,
    convert_fallible_adhoc_process_result,
    merge_extra_sandbox_contents,
    parse_relative_directory,
    prepare_env_vars,
    resolve_execution_environment,
)
from pants.core.util_rules.adhoc_process_support import rules as adhoc_process_support_rules
from pants.core.util_rules.system_binaries import (
    BashBinary,
    BinaryShimsRequest,
    create_binary_shims,
)
from pants.engine.environment import EnvironmentName
from pants.engine.fs import PathGlobs
from pants.engine.internals.graph import resolve_target
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.intrinsics import digest_to_snapshot
from pants.engine.process import Process
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import (
    GeneratedSources,
    GenerateSourcesRequest,
    Target,
    WrappedTargetRequest,
)
from pants.engine.unions import UnionRule
from pants.util.docutil import bin_name
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class GenerateFilesFromShellCommandRequest(GenerateSourcesRequest):
    input = ShellCommandSourcesField
    output = FileSourceField


@dataclass(frozen=True)
class ShellCommandProcessFromTargetRequest:
    target: Target


@rule
async def prepare_process_request_from_target(
    request: ShellCommandProcessFromTargetRequest,
    shell_setup: ShellSetup.EnvironmentAware,
    bash: BashBinary,
    env_target: EnvironmentTarget,
) -> AdhocProcessRequest:
    shell_command = request.target

    description = f"the `{shell_command.alias}` at `{shell_command.address}`"

    working_directory = shell_command[ShellCommandWorkdirField].value
    assert working_directory is not None, "working_directory should always be a string"

    command = shell_command[ShellCommandCommandFieldBase].value
    if not command:
        raise ValueError(f"Missing `command` line in `{description}.")

    execution_environment = await resolve_execution_environment(
        ResolveExecutionDependenciesRequest(
            shell_command.address,
            shell_command.get(ShellCommandExecutionDependenciesField).value,
            shell_command.get(ShellCommandRunnableDependenciesField).value,
        ),
        **implicitly(),
    )

    dependencies_digest = execution_environment.digest

    output_files = shell_command.get(ShellCommandOutputFilesField).value or ()
    output_directories = shell_command.get(ShellCommandOutputDirectoriesField).value or ()

    # Resolve the `tools` field into a digest
    tools = shell_command.get(ShellCommandToolsField, default_raw_value=()).value or ()
    tools = tuple(tool for tool in tools if tool not in BASH_BUILTIN_COMMANDS)
    resolved_tools = await create_binary_shims(
        BinaryShimsRequest.for_binaries(
            *tools,
            rationale=f"execute {description}",
            search_path=shell_setup.executable_search_path,
        ),
        bash,
    )

    runnable_dependencies = execution_environment.runnable_dependencies
    extra_sandbox_contents: list[ExtraSandboxContents] = []
    extra_sandbox_contents.append(
        ExtraSandboxContents(
            digest=EMPTY_DIGEST,
            paths=(resolved_tools.path_component,),
            immutable_input_digests=FrozenDict(resolved_tools.immutable_input_digests or {}),
            append_only_caches=FrozenDict(),
            extra_env=FrozenDict(),
        )
    )

    if runnable_dependencies:
        extra_sandbox_contents.append(
            ExtraSandboxContents(
                digest=EMPTY_DIGEST,
                paths=(f"{{chroot}}/{runnable_dependencies.path_component}",),
                immutable_input_digests=runnable_dependencies.immutable_input_digests,
                append_only_caches=runnable_dependencies.append_only_caches,
                extra_env=runnable_dependencies.extra_env,
            )
        )

    merged_extras = await merge_extra_sandbox_contents(
        MergeExtraSandboxContents(tuple(extra_sandbox_contents))
    )

    env_vars = await prepare_env_vars(
        merged_extras.extra_env,
        shell_command.get(ShellCommandExtraEnvVarsField).value or (),
        extra_paths=merged_extras.paths,
        path_env_modify_mode=shell_command.get(ShellCommandPathEnvModifyModeField).enum_value,
        description_of_origin=f"`{ShellCommandExtraEnvVarsField.alias}` for `shell_command` target at `{shell_command.address}`",
    )

    append_only_caches = {
        **merged_extras.append_only_caches,
        **(shell_command.get(ShellCommandNamedCachesField).value or {}),
    }

    cache_scope = env_target.default_cache_scope
    maybe_override_cache_scope = shell_command.get(ShellCommandCacheScopeField).enum_value
    if maybe_override_cache_scope is not None:
        cache_scope = maybe_override_cache_scope

    workspace_invalidation_globs: PathGlobs | None = None
    workspace_invalidation_sources = (
        shell_command.get(ShellCommandWorkspaceInvalidationSourcesField).value or ()
    )
    if workspace_invalidation_sources:
        spec_path = shell_command.address.spec_path
        workspace_invalidation_globs = PathGlobs(
            globs=(os.path.join(spec_path, glob) for glob in workspace_invalidation_sources),
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin=f"`{ShellCommandWorkspaceInvalidationSourcesField.alias}` for `shell_command` target at `{shell_command.address}`",
        )

    outputs_match_mode = shell_command.get(ShellCommandOutputsMatchMode).enum_value

    return AdhocProcessRequest(
        description=description,
        address=shell_command.address,
        working_directory=working_directory,
        root_output_directory=shell_command.get(ShellCommandOutputRootDirField).value or "",
        argv=(bash.path, "-c", command, shell_command.address.spec),
        timeout=shell_command.get(ShellCommandTimeoutField).value,
        input_digest=dependencies_digest,
        output_files=output_files,
        output_directories=output_directories,
        append_only_caches=FrozenDict(append_only_caches),
        env_vars=env_vars,
        immutable_input_digests=FrozenDict.frozen(merged_extras.immutable_input_digests),
        log_on_process_errors=_LOG_ON_PROCESS_ERRORS,
        log_output=shell_command[ShellCommandLogOutputField].value,
        capture_stdout_file=None,
        capture_stderr_file=None,
        workspace_invalidation_globs=workspace_invalidation_globs,
        cache_scope=cache_scope,
        use_working_directory_as_base_for_output_captures=env_target.use_working_directory_as_base_for_output_captures,
        outputs_match_error_behavior=outputs_match_mode.glob_match_error_behavior,
        outputs_match_conjunction=outputs_match_mode.glob_expansion_conjunction,
    )


class RunShellCommand(RunFieldSet):
    required_fields = (
        RunShellCommandCommandField,
        RunShellCommandWorkdirField,
    )
    run_in_sandbox_behavior = RunInSandboxBehavior.NOT_SUPPORTED


@dataclass(frozen=True)
class RunShellCommandBuild(RunFieldSet):
    """Run a shell_command target interactively with explicit tool dependencies."""

    required_fields = (ShellCommandCommandField,)
    run_in_sandbox_behavior = RunInSandboxBehavior.RUN_REQUEST_HERMETIC

    command: ShellCommandCommandField
    execution_dependencies: ShellCommandExecutionDependenciesField
    runnable_dependencies: ShellCommandRunnableDependenciesField
    tools: ShellCommandToolsField
    workdir: ShellCommandWorkdirField


@rule(desc="Running shell command", level=LogLevel.DEBUG)
async def shell_command_in_sandbox(
    request: GenerateFilesFromShellCommandRequest,
) -> GeneratedSources:
    shell_command = request.protocol_target
    environment_name = await resolve_environment_name(
        EnvironmentNameRequest.from_target(shell_command),
        **implicitly(),
    )

    adhoc_result = await convert_fallible_adhoc_process_result(
        **implicitly(
            {
                environment_name: EnvironmentName,
                ShellCommandProcessFromTargetRequest(
                    shell_command
                ): ShellCommandProcessFromTargetRequest,
            }
        )
    )

    output = await digest_to_snapshot(adhoc_result.adjusted_digest)
    return GeneratedSources(output)


async def _interactive_shell_command(
    shell_command: Target,
    bash: BashBinary,
) -> Process:
    description = f"the `{shell_command.alias}` at `{shell_command.address}`"
    working_directory = shell_command[RunShellCommandWorkdirField].value

    if working_directory is None:
        raise ValueError("Working directory must be not be `None` for interactive processes.")

    command = shell_command[RunShellCommandCommandField].value
    if not command:
        raise ValueError(f"Missing `command` line in `{description}.")

    command_env = {
        "CHROOT": "{chroot}",
    }

    execution_environment = await resolve_execution_environment(
        ResolveExecutionDependenciesRequest(
            shell_command.address,
            shell_command.get(ShellCommandExecutionDependenciesField).value,
            shell_command.get(ShellCommandRunnableDependenciesField).value,
        ),
        bash,
    )
    dependencies_digest = execution_environment.digest

    relpath = parse_relative_directory(working_directory, shell_command.address)
    boot_script = f"cd {shlex.quote(relpath)}; " if relpath != "" else ""

    return Process(
        argv=(
            bash.path,
            "-c",
            boot_script + command,
            f"{bin_name()} run {shell_command.address.spec} --",
        ),
        description=f"Running {description}",
        env=command_env,
        input_digest=dependencies_digest,
    )


@rule
async def run_shell_command_request(bash: BashBinary, shell_command: RunShellCommand) -> RunRequest:
    wrapped_tgt = await resolve_target(
        WrappedTargetRequest(shell_command.address, description_of_origin="<infallible>"),
        **implicitly(),
    )
    process = await _interactive_shell_command(wrapped_tgt.target, bash)
    return RunRequest(
        digest=process.input_digest,
        args=process.argv,
        extra_env=process.env,
    )


@rule(desc="Running shell_command target", level=LogLevel.DEBUG)
async def run_shell_command_build_request(
    field_set: RunShellCommandBuild,
    bash: BashBinary,
    shell_setup: ShellSetup.EnvironmentAware,
) -> RunRequest:
    """Execute a shell_command target interactively with explicit tool dependencies."""

    command = field_set.command.value
    if not command:
        raise ValueError(
            f"Missing `command` field in `shell_command` target at `{field_set.address}`."
        )

    # Resolve execution environment with all dependencies
    execution_environment = await resolve_execution_environment(
        ResolveExecutionDependenciesRequest(
            field_set.address,
            field_set.execution_dependencies.value,
            field_set.runnable_dependencies.value,
        ),
        **implicitly(),
    )

    # Resolve tools into binary shims
    tools = field_set.tools.value or ()
    tools = tuple(tool for tool in tools if tool not in BASH_BUILTIN_COMMANDS)
    resolved_tools = await create_binary_shims(
        BinaryShimsRequest.for_binaries(
            *tools,
            rationale=f"execute `shell_command` at `{field_set.address}`",
            search_path=shell_setup.executable_search_path,
        ),
        bash,
    )

    # Prepare extra sandbox contents with tools and runnable dependencies
    runnable_dependencies = execution_environment.runnable_dependencies
    extra_sandbox_contents: list[ExtraSandboxContents] = []

    # Add tools to the environment
    extra_sandbox_contents.append(
        ExtraSandboxContents(
            digest=EMPTY_DIGEST,
            paths=(resolved_tools.path_component,),
            immutable_input_digests=FrozenDict(resolved_tools.immutable_input_digests or {}),
            append_only_caches=FrozenDict(),
            extra_env=FrozenDict(),
        )
    )

    # Add runnable dependencies
    if runnable_dependencies:
        extra_sandbox_contents.append(
            ExtraSandboxContents(
                digest=EMPTY_DIGEST,
                paths=(f"{{chroot}}/{runnable_dependencies.path_component}",),
                immutable_input_digests=runnable_dependencies.immutable_input_digests,
                append_only_caches=runnable_dependencies.append_only_caches,
                extra_env=runnable_dependencies.extra_env,
            )
        )

    merged_extras = await merge_extra_sandbox_contents(
        MergeExtraSandboxContents(tuple(extra_sandbox_contents))
    )

    # Prepare environment variables
    env_vars = await prepare_env_vars(
        merged_extras.extra_env,
        (),  # No extra env vars field for run
        extra_paths=merged_extras.paths,
        description_of_origin=f"`shell_command` target at `{field_set.address}`",
    )

    # Parse working directory
    working_directory = field_set.workdir.value
    if working_directory is None:
        working_directory = "."

    relpath = parse_relative_directory(working_directory, field_set.address)
    boot_script = f"cd {shlex.quote(relpath)}; " if relpath != "" else ""

    return RunRequest(
        digest=execution_environment.digest,
        args=(
            bash.path,
            "-c",
            boot_script + command,
            f"{bin_name()} run {field_set.address.spec} --",
        ),
        extra_env=env_vars,
        immutable_input_digests=FrozenDict.frozen(merged_extras.immutable_input_digests),
        append_only_caches=FrozenDict.frozen(merged_extras.append_only_caches),
    )


def rules():
    return [
        *collect_rules(),
        *adhoc_process_support_rules(),
        UnionRule(GenerateSourcesRequest, GenerateFilesFromShellCommandRequest),
        *RunShellCommand.rules(),
        *RunShellCommandBuild.rules(),
    ]


_LOG_ON_PROCESS_ERRORS = FrozenDict(
    {
        127: (
            f"`{ShellCommandTarget.alias}` requires the names of any external commands used by this "
            f"shell command to be specified in the `{ShellCommandToolsField.alias}` field. If "
            f"`bash` cannot find a tool, add it to the `{ShellCommandToolsField.alias}` field."
        )
    }
)
