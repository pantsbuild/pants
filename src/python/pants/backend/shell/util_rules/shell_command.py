# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.shell.subsystems.shell_setup import ShellSetup
from pants.backend.shell.target_types import (
    ShellCommandCommandField,
    ShellCommandExtraEnvVarsField,
    ShellCommandIsInteractiveField,
    ShellCommandLogOutputField,
    ShellCommandOutputRootDirField,
    ShellCommandSourcesField,
    ShellCommandTimeoutField,
    ShellCommandToolsField,
    ShellCommandWorkdirField,
)
from pants.backend.shell.util_rules.adhoc_process_support import (
    ShellCommandProcessRequest,
    _adjust_root_output_directory,
    _execution_environment_from_dependencies,
    _parse_outputs_from_command,
)
from pants.backend.shell.util_rules.adhoc_process_support import (
    rules as adhoc_process_support_rules,
)
from pants.backend.shell.util_rules.builtin import BASH_BUILTIN_COMMANDS
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior, RunRequest
from pants.core.target_types import FileSourceField
from pants.core.util_rules.environments import EnvironmentNameRequest
from pants.core.util_rules.system_binaries import BinaryShims, BinaryShimsRequest
from pants.engine.environment import EnvironmentName
from pants.engine.fs import Digest, Snapshot
from pants.engine.process import FallibleProcessResult, Process, ProcessResult, ProductDescription
from pants.engine.rules import Get, collect_rules, rule, rule_helper
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


@rule_helper
async def _prepare_process_request_from_target(
    shell_command: Target, shell_setup: ShellSetup.EnvironmentAware
) -> ShellCommandProcessRequest:
    description = f"the `{shell_command.alias}` at `{shell_command.address}`"

    interactive = shell_command.has_field(ShellCommandIsInteractiveField)
    working_directory = shell_command[ShellCommandWorkdirField].value

    if interactive and not working_directory:
        working_directory = "."

    command = shell_command[ShellCommandCommandField].value
    if not command:
        raise ValueError(f"Missing `command` line in `{description}.")

    dependencies_digest = await _execution_environment_from_dependencies(shell_command)

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

    immutable_input_digests = resolved_tools.immutable_input_digests
    supplied_env_var_values = {"PATH": resolved_tools.path_component}

    return ShellCommandProcessRequest(
        description=description,
        address=shell_command.address,
        shell_name=shell_command.address.spec,
        interactive=interactive,
        working_directory=working_directory,
        command=command,
        timeout=shell_command.get(ShellCommandTimeoutField).value,
        input_digest=dependencies_digest,
        output_files=output_files,
        output_directories=output_directories,
        fetch_env_vars=shell_command.get(ShellCommandExtraEnvVarsField).value or (),
        append_only_caches=None,
        supplied_env_var_values=FrozenDict(supplied_env_var_values),
        immutable_input_digests=FrozenDict(immutable_input_digests),
    )


@rule
async def prepare_process_request_from_target(
    request: ShellCommandProcessFromTargetRequest,
    shell_setup: ShellSetup.EnvironmentAware,
) -> Process:
    scpr = await _prepare_process_request_from_target(request.target, shell_setup)
    return await Get(Process, ShellCommandProcessRequest, scpr)


class RunShellCommand(RunFieldSet):
    required_fields = (
        ShellCommandCommandField,
        ShellCommandWorkdirField,
    )
    run_in_sandbox_behavior = RunInSandboxBehavior.NOT_SUPPORTED


@rule(desc="Running shell command", level=LogLevel.DEBUG)
async def run_shell_command(
    request: GenerateFilesFromShellCommandRequest,
) -> GeneratedSources:
    shell_command = request.protocol_target
    environment_name = await Get(
        EnvironmentName, EnvironmentNameRequest, EnvironmentNameRequest.from_target(shell_command)
    )

    fallible_result = await Get(
        FallibleProcessResult,
        {
            environment_name: EnvironmentName,
            ShellCommandProcessFromTargetRequest(
                shell_command
            ): ShellCommandProcessFromTargetRequest,
        },
    )

    if fallible_result.exit_code == 127:
        logger.error(
            f"`{shell_command.alias}` requires the names of any external commands used by this "
            f"shell command to be specified in the `{ShellCommandToolsField.alias}` field. If "
            f"`bash` cannot find a tool, add it to the `{ShellCommandToolsField.alias}` field."
        )

    result = await Get(
        ProcessResult,
        {
            fallible_result: FallibleProcessResult,
            ProductDescription(
                f"the `{shell_command.alias}` at `{shell_command.address}`"
            ): ProductDescription,
        },
    )

    if shell_command[ShellCommandLogOutputField].value:
        if result.stdout:
            logger.info(result.stdout.decode())
        if result.stderr:
            logger.warning(result.stderr.decode())

    working_directory = shell_command[ShellCommandWorkdirField].value or ""
    root_output_directory = shell_command[ShellCommandOutputRootDirField].value or ""
    adjusted = await _adjust_root_output_directory(
        result.output_digest, shell_command.address, working_directory, root_output_directory
    )
    output = await Get(Snapshot, Digest, adjusted)
    return GeneratedSources(output)


@rule
async def run_shell_command_request(shell_command: RunShellCommand) -> RunRequest:
    wrapped_tgt = await Get(
        WrappedTarget,
        WrappedTargetRequest(shell_command.address, description_of_origin="<infallible>"),
    )
    process = await Get(
        Process,
        ShellCommandProcessFromTargetRequest(wrapped_tgt.target),
    )
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
