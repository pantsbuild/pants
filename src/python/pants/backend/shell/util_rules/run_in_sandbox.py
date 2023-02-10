# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
import shlex

from pants.backend.shell.target_types import (
    RunInSandboxArgumentsField,
    RunInSandboxRunnableField,
    RunInSandboxSourcesField,
    RunInSandboxStderrFilenameField,
    RunInSandboxStdoutFilenameField,
    ShellCommandLogOutputField,
    ShellCommandOutputRootDirField,
    ShellCommandWorkdirField,
)
from pants.backend.shell.util_rules.adhoc_process_support import (
    AdhocProcessResult,
    ShellCommandProcessRequest,
    _execution_environment_from_dependencies,
    _parse_outputs_from_command,
)
from pants.backend.shell.util_rules.adhoc_process_support import (
    rules as adhoc_process_support_rules,
)
from pants.build_graph.address import Address, AddressInput
from pants.core.goals.run import RunFieldSet, RunInSandboxRequest
from pants.core.target_types import FileSourceField
from pants.core.util_rules.environments import EnvironmentNameRequest
from pants.engine.addresses import Addresses
from pants.engine.environment import EnvironmentName
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests, Snapshot
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    GeneratedSources,
    GenerateSourcesRequest,
    Targets,
)
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class GenerateFilesFromRunInSandboxRequest(GenerateSourcesRequest):
    input = RunInSandboxSourcesField
    output = FileSourceField


@rule(desc="Running run_in_sandbox target", level=LogLevel.DEBUG)
async def run_in_sandbox_request(
    request: GenerateFilesFromRunInSandboxRequest,
) -> GeneratedSources:
    shell_command = request.protocol_target
    description = f"the `{shell_command.alias}` at {shell_command.address}"
    environment_name = await Get(
        EnvironmentName, EnvironmentNameRequest, EnvironmentNameRequest.from_target(shell_command)
    )

    runnable_address_str = shell_command[RunInSandboxRunnableField].value
    if not runnable_address_str:
        raise Exception(f"Must supply a value for `runnable` for {description}.")

    runnable_address = await Get(
        Address,
        AddressInput,
        AddressInput.parse(
            runnable_address_str,
            relative_to=shell_command.address.spec_path,
            description_of_origin=f"The `{RunInSandboxRunnableField.alias}` field of {description}",
        ),
    )

    addresses = Addresses((runnable_address,))
    addresses.expect_single()

    runnable_targets = await Get(Targets, Addresses, addresses)
    field_sets = await Get(
        FieldSetsPerTarget, FieldSetsPerTargetRequest(RunFieldSet, runnable_targets)
    )
    run_field_set: RunFieldSet = field_sets.field_sets[0]

    working_directory = shell_command[ShellCommandWorkdirField].value or ""
    root_output_directory = shell_command[ShellCommandOutputRootDirField].value or ""

    # Must be run in target environment so that the binaries/envvars match the execution
    # environment when we actually run the process.
    run_request = await Get(
        RunInSandboxRequest, {environment_name: EnvironmentName, run_field_set: RunFieldSet}
    )

    dependencies_digest = await _execution_environment_from_dependencies(shell_command)

    input_digest = await Get(Digest, MergeDigests((dependencies_digest, run_request.digest)))

    output_files, output_directories = _parse_outputs_from_command(shell_command, description)

    extra_args = shell_command.get(RunInSandboxArgumentsField).value or ()

    process_request = ShellCommandProcessRequest(
        description=description,
        address=shell_command.address,
        shell_name=shell_command.address.spec,
        working_directory=working_directory,
        root_output_directory=root_output_directory,
        command=" ".join(shlex.quote(arg) for arg in (run_request.args + extra_args)),
        timeout=None,
        input_digest=input_digest,
        immutable_input_digests=FrozenDict(run_request.immutable_input_digests or {}),
        append_only_caches=FrozenDict(run_request.append_only_caches or {}),
        output_files=output_files,
        output_directories=output_directories,
        fetch_env_vars=(),
        supplied_env_var_values=FrozenDict(**run_request.extra_env),
        log_on_process_errors=None,
        log_output=shell_command[ShellCommandLogOutputField].value,
    )

    adhoc_result = await Get(
        AdhocProcessResult,
        {
            environment_name: EnvironmentName,
            process_request: ShellCommandProcessRequest,
        },
    )

    result = adhoc_result.process_result
    adjusted = adhoc_result.adjusted_digest

    extras = (
        (shell_command[RunInSandboxStdoutFilenameField].value, result.stdout),
        (shell_command[RunInSandboxStderrFilenameField].value, result.stderr),
    )
    extra_contents = {i: j for i, j in extras if i}

    if extra_contents:
        extra_digest = await Get(
            Digest,
            CreateDigest(FileContent(name, content) for name, content in extra_contents.items()),
        )
        adjusted = await Get(Digest, MergeDigests((adjusted, extra_digest)))

    output = await Get(Snapshot, Digest, adjusted)
    return GeneratedSources(output)


def rules():
    return [
        *collect_rules(),
        *adhoc_process_support_rules(),
        UnionRule(GenerateSourcesRequest, GenerateFilesFromRunInSandboxRequest),
    ]
