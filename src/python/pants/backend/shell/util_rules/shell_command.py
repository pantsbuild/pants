# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import itertools
import logging
import os
import re
import shlex
from dataclasses import dataclass
from textwrap import dedent  # noqa: PNT20

from pants.backend.shell.subsystems.shell_setup import ShellSetup
from pants.backend.shell.target_types import (
    RunInSandboxArgumentsField,
    RunInSandboxRunnableField,
    RunInSandboxSourcesField,
    ShellCommandCommandField,
    ShellCommandExecutionDependenciesField,
    ShellCommandExtraEnvVarsField,
    ShellCommandIsInteractiveField,
    ShellCommandLogOutputField,
    ShellCommandOutputDependenciesField,
    ShellCommandOutputDirectoriesField,
    ShellCommandOutputFilesField,
    ShellCommandOutputsField,
    ShellCommandSourcesField,
    ShellCommandTimeoutField,
    ShellCommandToolsField,
    ShellCommandWorkdirField,
)
from pants.backend.shell.util_rules.builtin import BASH_BUILTIN_COMMANDS
from pants.base.deprecated import warn_or_error
from pants.build_graph.address import Address, AddressInput
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior, RunInSandboxRequest, RunRequest
from pants.core.target_types import FileSourceField
from pants.core.util_rules.environments import EnvironmentNameRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.system_binaries import (
    BashBinary,
    BinaryNotFoundError,
    BinaryPathRequest,
    BinaryPaths,
)
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.environment import EnvironmentName
from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Digest, Directory, MergeDigests, Snapshot
from pants.engine.process import FallibleProcessResult, Process, ProcessResult, ProductDescription
from pants.engine.rules import Get, MultiGet, collect_rules, rule, rule_helper
from pants.engine.target import (
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    GeneratedSources,
    GenerateSourcesRequest,
    SourcesField,
    Target,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
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


class GenerateFilesFromRunInSandboxRequest(GenerateSourcesRequest):
    input = RunInSandboxSourcesField
    output = FileSourceField


@dataclass(frozen=True)
class ShellCommandProcessRequest:
    description: str
    shell_name: str
    interactive: bool
    working_directory: str | None
    command: str
    timeout: int | None
    tools: tuple[str, ...]
    input_digest: Digest
    immutable_input_digests: FrozenDict[str, Digest] | None
    append_only_caches: FrozenDict[str, str] | None
    output_files: tuple[str, ...]
    output_directories: tuple[str, ...]
    fetch_env_vars: tuple[str, ...]
    supplied_env_var_values: FrozenDict[str, str] | None


@dataclass(frozen=True)
class ShellCommandProcessFromTargetRequest:
    target: Target


@rule_helper
async def _prepare_process_request_from_target(shell_command: Target) -> ShellCommandProcessRequest:
    description = f"the `{shell_command.alias}` at `{shell_command.address}`"

    interactive = shell_command.has_field(ShellCommandIsInteractiveField)
    working_directory = _parse_working_directory(
        shell_command[ShellCommandWorkdirField].value or "", shell_command.address
    )

    if interactive and not working_directory:
        working_directory = "."

    command = shell_command[ShellCommandCommandField].value
    if not command:
        raise ValueError(f"Missing `command` line in `{description}.")

    dependencies_digest = await _execution_environment_from_dependencies(shell_command)

    output_files, output_directories = _parse_outputs_from_command(shell_command, description)

    return ShellCommandProcessRequest(
        description=description,
        shell_name=shell_command.address.spec,
        interactive=interactive,
        working_directory=working_directory,
        command=command,
        timeout=shell_command.get(ShellCommandTimeoutField).value,
        tools=shell_command.get(ShellCommandToolsField, default_raw_value=()).value or (),
        input_digest=dependencies_digest,
        output_files=output_files,
        output_directories=output_directories,
        fetch_env_vars=shell_command.get(ShellCommandExtraEnvVarsField).value or (),
        append_only_caches=None,
        supplied_env_var_values=None,
        immutable_input_digests=None,
    )


@rule_helper
async def _execution_environment_from_dependencies(shell_command: Target) -> Digest:

    runtime_dependencies_defined = (
        shell_command.get(ShellCommandExecutionDependenciesField).value is not None
    )

    any_dependencies_defined = (
        shell_command.get(ShellCommandOutputDependenciesField).value is not None
    )

    # If we're specifying the `dependencies` as relevant to the execution environment, then include
    # this command as a root for the transitive dependency search for execution dependencies.
    maybe_this_target = (shell_command.address,) if not runtime_dependencies_defined else ()

    # Always include the execution dependencies that were specified
    if runtime_dependencies_defined:
        runtime_dependencies = await Get(
            Addresses,
            UnparsedAddressInputs,
            shell_command.get(ShellCommandExecutionDependenciesField).to_unparsed_address_inputs(),
        )
    elif any_dependencies_defined:
        runtime_dependencies = Addresses()
        warn_or_error(
            "2.17.0.dev0",
            (
                "Using `dependencies` to specify execution-time dependencies for "
                "`experimental_shell_command` "
            ),
            (
                "To clear this warning, use the `output_dependencies` and `execution_dependencies`"
                "fields. Set `execution_dependencies=()` if you have no execution-time "
                "dependencies."
            ),
            print_warning=True,
        )
    else:
        runtime_dependencies = Addresses()

    transitive = await Get(
        TransitiveTargets,
        TransitiveTargetsRequest(itertools.chain(maybe_this_target, runtime_dependencies)),
    )

    all_dependencies = (
        *(i for i in transitive.roots if i is not shell_command),
        *transitive.dependencies,
    )

    sources, pkgs_per_target = await MultiGet(
        Get(
            SourceFiles,
            SourceFilesRequest(
                sources_fields=[tgt.get(SourcesField) for tgt in all_dependencies],
                for_sources_types=(SourcesField, FileSourceField),
                enable_codegen=True,
            ),
        ),
        Get(
            FieldSetsPerTarget,
            FieldSetsPerTargetRequest(PackageFieldSet, all_dependencies),
        ),
    )

    packages = await MultiGet(
        Get(BuiltPackage, PackageFieldSet, field_set) for field_set in pkgs_per_target.field_sets
    )

    dependencies_digest = await Get(
        Digest, MergeDigests([sources.snapshot.digest, *(pkg.digest for pkg in packages)])
    )

    return dependencies_digest


def _parse_outputs_from_command(
    shell_command: Target, description: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    outputs = shell_command.get(ShellCommandOutputsField).value or ()
    output_files = shell_command.get(ShellCommandOutputFilesField).value or ()
    output_directories = shell_command.get(ShellCommandOutputDirectoriesField).value or ()
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
async def prepare_process_request_from_target(
    request: ShellCommandProcessFromTargetRequest,
) -> Process:
    scpr = await _prepare_process_request_from_target(request.target)
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

    output = await Get(Snapshot, Digest, result.output_digest)
    return GeneratedSources(output)


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

    working_directory = _parse_working_directory(
        shell_command[ShellCommandWorkdirField].value or "", shell_command.address
    )

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
        shell_name=shell_command.address.spec,
        interactive=False,
        working_directory=working_directory,
        command=" ".join(shlex.quote(arg) for arg in (run_request.args + extra_args)),
        timeout=None,
        tools=(),
        input_digest=input_digest,
        immutable_input_digests=FrozenDict(run_request.immutable_input_digests or {}),
        append_only_caches=FrozenDict(run_request.append_only_caches or {}),
        output_files=output_files,
        output_directories=output_directories,
        fetch_env_vars=(),
        supplied_env_var_values=FrozenDict(**run_request.extra_env),
    )

    result = await Get(
        ProcessResult,
        {
            environment_name: EnvironmentName,
            process_request: ShellCommandProcessRequest,
        },
    )

    if shell_command[ShellCommandLogOutputField].value:
        if result.stdout:
            logger.info(result.stdout.decode())
        if result.stderr:
            logger.warning(result.stderr.decode())

    output = await Get(Snapshot, Digest, result.output_digest)
    return GeneratedSources(output)


def _shell_tool_safe_env_name(tool_name: str) -> str:
    """Replace any characters not suitable in an environment variable name with `_`."""
    return re.sub(r"\W", "_", tool_name)


@rule_helper
async def _shell_command_tools(
    shell_setup: ShellSetup.EnvironmentAware, tools: tuple[str, ...], rationale: str
) -> dict[str, str]:

    search_path = shell_setup.executable_search_path
    tool_requests = [
        BinaryPathRequest(
            binary_name=tool,
            search_path=search_path,
        )
        for tool in sorted({*tools, *["mkdir", "ln"]})
        if tool not in BASH_BUILTIN_COMMANDS
    ]
    tool_paths = await MultiGet(
        Get(BinaryPaths, BinaryPathRequest, request) for request in tool_requests
    )

    paths: dict[str, str] = {}

    for binary, tool_request in zip(tool_paths, tool_requests):
        if binary.first_path:
            paths[_shell_tool_safe_env_name(tool_request.binary_name)] = binary.first_path.path
        else:
            raise BinaryNotFoundError.from_request(
                tool_request,
                rationale=rationale,
            )

    return paths


@rule
async def prepare_shell_command_process(
    shell_setup: ShellSetup.EnvironmentAware,
    shell_command: ShellCommandProcessRequest,
    bash: BashBinary,
) -> Process:

    description = shell_command.description
    shell_name = shell_command.shell_name
    interactive = shell_command.interactive
    working_directory = shell_command.working_directory
    command = shell_command.command
    timeout: int | None = shell_command.timeout
    tools = shell_command.tools
    output_files = shell_command.output_files
    output_directories = shell_command.output_directories
    fetch_env_vars = shell_command.fetch_env_vars
    supplied_env_vars = shell_command.supplied_env_var_values or FrozenDict()
    append_only_caches = shell_command.append_only_caches or FrozenDict()
    immutable_input_digests = shell_command.immutable_input_digests

    if interactive:
        command_env = {
            "CHROOT": "{chroot}",
        }
    else:
        resolved_tools = await _shell_command_tools(shell_setup, tools, f"execute {description}")
        tools = tuple(tool for tool in sorted(resolved_tools))

        command_env = {"TOOLS": " ".join(tools), **resolved_tools}

    extra_env = await Get(EnvironmentVars, EnvironmentVarsRequest(fetch_env_vars))
    command_env.update(extra_env)

    if supplied_env_vars:
        command_env.update(supplied_env_vars)

    input_snapshot = await Get(Snapshot, Digest, shell_command.input_digest)

    if interactive or not working_directory or working_directory in input_snapshot.dirs:
        # Needed to ensure that underlying filesystem does not change during run
        work_dir = EMPTY_DIGEST
    else:
        work_dir = await Get(Digest, CreateDigest([Directory(working_directory)]))

    input_digest = await Get(Digest, MergeDigests([shell_command.input_digest, work_dir]))

    if interactive:
        _working_directory = working_directory or "."
        relpath = os.path.relpath(
            _working_directory or ".", start="/" if os.path.isabs(_working_directory) else "."
        )
        boot_script = f"cd {shlex.quote(relpath)}; " if relpath != "." else ""
    else:
        # Setup bin_relpath dir with symlinks to all requested tools, so that we can use PATH, force
        # symlinks to avoid issues with repeat runs using the __run.sh script in the sandbox.
        bin_relpath = ".bin"
        boot_script = ";".join(
            dedent(
                f"""\
                $mkdir -p {bin_relpath}
                for tool in $TOOLS; do $ln -sf ${{!tool}} {bin_relpath}; done
                export PATH="$PWD/{bin_relpath}"
                """
            ).split("\n")
        )

    proc = Process(
        argv=(bash.path, "-c", boot_script + command, shell_name),
        description=f"Running {description}",
        env=command_env,
        input_digest=input_digest,
        output_directories=output_directories,
        output_files=output_files,
        timeout_seconds=timeout,
        working_directory=working_directory,
        append_only_caches=append_only_caches,
        immutable_input_digests=immutable_input_digests,
    )

    if not interactive:
        return _output_at_build_root(proc, bash)
    else:
        # `InteractiveProcess`es don't need to be wrapped since files aren't being captured.
        return proc


def _output_at_build_root(process: Process, bash: BashBinary) -> Process:

    working_directory = process.working_directory or ""

    output_directories = process.output_directories
    output_files = process.output_files
    if working_directory:
        output_directories = tuple(os.path.join(working_directory, d) for d in output_directories)
        output_files = tuple(os.path.join(working_directory, d) for d in output_files)

    cd = f"cd {shlex.quote(working_directory)} && " if working_directory else ""
    shlexed_argv = " ".join(shlex.quote(arg) for arg in process.argv)
    new_argv = (bash.path, "-c", f"{cd}{shlexed_argv}")

    return dataclasses.replace(
        process,
        argv=new_argv,
        working_directory=None,
        output_directories=output_directories,
        output_files=output_files,
    )


def _parse_working_directory(workdir_in: str, address: Address) -> str:
    """Convert the `workdir` field into something that can be understood by `Process`."""

    reldir = address.spec_path

    if workdir_in == ".":
        return reldir
    elif workdir_in.startswith("./"):
        return os.path.join(reldir, workdir_in[2:])
    elif workdir_in.startswith("/"):
        return workdir_in[1:]
    else:
        return workdir_in


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
        UnionRule(GenerateSourcesRequest, GenerateFilesFromShellCommandRequest),
        UnionRule(GenerateSourcesRequest, GenerateFilesFromRunInSandboxRequest),
        *RunShellCommand.rules(),
    ]
