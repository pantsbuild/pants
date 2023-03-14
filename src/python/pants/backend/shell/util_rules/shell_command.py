# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
import shlex
from dataclasses import dataclass

from pants.backend.shell.subsystems.shell_setup import ShellSetup
from pants.backend.shell.target_types import (
    RunShellCommandWorkdirField,
    ShellCommandCommandField,
    ShellCommandExecutionDependenciesField,
    ShellCommandExtraEnvVarsField,
    ShellCommandLogOutputField,
    ShellCommandOutputDependenciesField,
    ShellCommandOutputDirectoriesField,
    ShellCommandOutputFilesField,
    ShellCommandOutputRootDirField,
    ShellCommandOutputsField,
    ShellCommandRunnableDependenciesField,
    ShellCommandSourcesField,
    ShellCommandTarget,
    ShellCommandTimeoutField,
    ShellCommandToolsField,
    ShellCommandWorkdirField,
)
from pants.backend.shell.util_rules.builtin import BASH_BUILTIN_COMMANDS
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior, RunRequest
from pants.core.target_types import FileSourceField
from pants.core.util_rules.adhoc_process_support import (
    AdhocProcessRequest,
    AdhocProcessResult,
    ExtraSandboxContents,
    MergeExtraSandboxContents,
    ResolvedExecutionDependencies,
    ResolveExecutionDependenciesRequest,
)
from pants.core.util_rules.adhoc_process_support import rules as adhoc_process_support_rules
from pants.core.util_rules.environments import EnvironmentNameRequest
from pants.core.util_rules.system_binaries import BashBinary, BinaryShims, BinaryShimsRequest
from pants.engine.environment import EnvironmentName
from pants.engine.fs import Digest, Snapshot
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.process import Process
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    GeneratedSources,
    GenerateSourcesRequest,
    Target,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class GenerateFilesFromShellCommandRequest(GenerateSourcesRequest):
    input = ShellCommandSourcesField
    output = FileSourceField


@dataclass(frozen=True)
class ShellCommandProcessFromTargetRequest:
    target: Target


async def _prepare_process_request_from_target(
    shell_command: Target,
    shell_setup: ShellSetup.EnvironmentAware,
    bash: BashBinary,
) -> AdhocProcessRequest:
    description = f"the `{shell_command.alias}` at `{shell_command.address}`"

    working_directory = shell_command[ShellCommandWorkdirField].value

    if not working_directory:
        working_directory = "."

    command = shell_command[ShellCommandCommandField].value
    if not command:
        raise ValueError(f"Missing `command` line in `{description}.")

    execution_environment = await Get(
        ResolvedExecutionDependencies,
        ResolveExecutionDependenciesRequest(
            shell_command.address,
            shell_command.get(ShellCommandExecutionDependenciesField).value,
            shell_command.get(ShellCommandOutputDependenciesField).value,
            shell_command.get(ShellCommandRunnableDependenciesField).value,
        ),
    )
    dependencies_digest = execution_environment.digest

    output_files, output_directories = _parse_outputs_from_command(shell_command, description)

    # Resolve the `tools` field into a digest
    tools = shell_command.get(ShellCommandToolsField, default_raw_value=()).value or ()
    tools = tuple(tool for tool in tools if tool not in BASH_BUILTIN_COMMANDS)

    resolved_tools = await Get(
        BinaryShims,
        BinaryShimsRequest.for_binaries(
            *tools,
            rationale=f"execute {description}",
            search_path=shell_setup.executable_search_path,
        ),
    )

    runnable_dependencies = execution_environment.runnable_dependencies
    extra_sandbox_contents = []

    extra_sandbox_contents.append(
        ExtraSandboxContents(
            EMPTY_DIGEST,
            resolved_tools.path_component,
            FrozenDict(resolved_tools.immutable_input_digests or {}),
            FrozenDict(),
            FrozenDict(),
        )
    )

    if runnable_dependencies:
        extra_sandbox_contents.append(
            ExtraSandboxContents(
                EMPTY_DIGEST,
                f"{{chroot}}/{runnable_dependencies.path_component}",
                runnable_dependencies.immutable_input_digests,
                runnable_dependencies.append_only_caches,
                runnable_dependencies.extra_env,
            )
        )

    merged_extras = await Get(
        ExtraSandboxContents, MergeExtraSandboxContents(tuple(extra_sandbox_contents))
    )
    extra_env = dict(merged_extras.extra_env)
    if merged_extras.path:
        extra_env["PATH"] = merged_extras.path

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
        fetch_env_vars=shell_command.get(ShellCommandExtraEnvVarsField).value or (),
        append_only_caches=FrozenDict.frozen(merged_extras.append_only_caches),
        supplied_env_var_values=FrozenDict(extra_env),
        immutable_input_digests=FrozenDict.frozen(merged_extras.immutable_input_digests),
        log_on_process_errors=_LOG_ON_PROCESS_ERRORS,
        log_output=shell_command[ShellCommandLogOutputField].value,
    )


def _parse_outputs_from_command(
    adhoc_process_target: Target, description: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    outputs = adhoc_process_target.get(ShellCommandOutputsField).value or ()
    output_files = adhoc_process_target.get(ShellCommandOutputFilesField).value or ()
    output_directories = adhoc_process_target.get(ShellCommandOutputDirectoriesField).value or ()
    if outputs and (output_files or output_directories):
        raise ValueError(
            "Both new-style `output_files` or `output_directories` and old-style `outputs` were "
            f"specified in {description}. To fix, move all values from `outputs` to "
            "`output_files` or `output_directories`."
        )
    elif outputs:
        output_files = tuple(f for f in outputs if not f.endswith("/"))
        output_directories = tuple(d for d in outputs if d.endswith("/"))
    return output_files, output_directories


@rule
async def run_adhoc_result_from_target(
    request: ShellCommandProcessFromTargetRequest,
    shell_setup: ShellSetup.EnvironmentAware,
    bash: BashBinary,
) -> AdhocProcessResult:
    scpr = await _prepare_process_request_from_target(request.target, shell_setup, bash)
    return await Get(AdhocProcessResult, AdhocProcessRequest, scpr)


@rule
async def prepare_process_request_from_target(
    request: ShellCommandProcessFromTargetRequest,
    shell_setup: ShellSetup.EnvironmentAware,
    bash: BashBinary,
) -> Process:
    # Needed to support `experimental_test_shell_command`
    scpr = await _prepare_process_request_from_target(request.target, shell_setup, bash)
    return await Get(Process, AdhocProcessRequest, scpr)


class RunShellCommand(RunFieldSet):
    required_fields = (
        ShellCommandCommandField,
        RunShellCommandWorkdirField,
    )
    run_in_sandbox_behavior = RunInSandboxBehavior.NOT_SUPPORTED


@rule(desc="Running shell command", level=LogLevel.DEBUG)
async def shell_command_in_sandbox(
    request: GenerateFilesFromShellCommandRequest,
) -> GeneratedSources:
    shell_command = request.protocol_target
    environment_name = await Get(
        EnvironmentName, EnvironmentNameRequest, EnvironmentNameRequest.from_target(shell_command)
    )

    adhoc_result = await Get(
        AdhocProcessResult,
        {
            environment_name: EnvironmentName,
            ShellCommandProcessFromTargetRequest(
                shell_command
            ): ShellCommandProcessFromTargetRequest,
        },
    )

    output = await Get(Snapshot, Digest, adhoc_result.adjusted_digest)
    return GeneratedSources(output)


async def _interactive_shell_command(
    shell_command: Target,
    bash: BashBinary,
) -> Process:
    description = f"the `{shell_command.alias}` at `{shell_command.address}`"
    shell_name = shell_command.address.spec
    working_directory = shell_command[RunShellCommandWorkdirField].value

    if working_directory is None:
        raise ValueError("Working directory must be not be `None` for interactive processes.")

    command = shell_command[ShellCommandCommandField].value
    if not command:
        raise ValueError(f"Missing `command` line in `{description}.")

    command_env = {
        "CHROOT": "{chroot}",
    }

    execution_environment = await Get(
        ResolvedExecutionDependencies,
        ResolveExecutionDependenciesRequest(
            shell_command.address,
            shell_command.get(ShellCommandExecutionDependenciesField).value,
            shell_command.get(ShellCommandOutputDependenciesField).value,
            shell_command.get(ShellCommandRunnableDependenciesField).value,
        ),
    )
    dependencies_digest = execution_environment.digest

    _working_directory = working_directory or "."
    relpath = os.path.relpath(
        _working_directory, start="/" if os.path.isabs(_working_directory) else "."
    )
    boot_script = f"cd {shlex.quote(relpath)}; " if relpath != "." else ""

    return Process(
        argv=(bash.path, "-c", boot_script + command, shell_name),
        description=f"Running {description}",
        env=command_env,
        input_digest=dependencies_digest,
        working_directory=working_directory,
    )


@rule
async def run_shell_command_request(bash: BashBinary, shell_command: RunShellCommand) -> RunRequest:
    wrapped_tgt = await Get(
        WrappedTarget,
        WrappedTargetRequest(shell_command.address, description_of_origin="<infallible>"),
    )
    process = await _interactive_shell_command(wrapped_tgt.target, bash)
    return RunRequest(
        digest=process.input_digest,
        args=process.argv,
        extra_env=process.env,
    )


def rules():
    return [
        *collect_rules(),
        *adhoc_process_support_rules(),
        UnionRule(GenerateSourcesRequest, GenerateFilesFromShellCommandRequest),
        *RunShellCommand.rules(),
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
