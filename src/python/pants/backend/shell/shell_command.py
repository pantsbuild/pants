# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
import re
import shlex
from dataclasses import dataclass
from textwrap import dedent

from pants.backend.shell.builtin import BASH_BUILTIN_COMMANDS
from pants.backend.shell.shell_setup import ShellSetup
from pants.backend.shell.target_types import (
    ShellCommandCommandField,
    ShellCommandLogOutputField,
    ShellCommandOutputsField,
    ShellCommandRunWorkdirField,
    ShellCommandSourcesField,
    ShellCommandTimeoutField,
    ShellCommandToolsField,
)
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.goals.run import RunFieldSet, RunRequest
from pants.core.target_types import FileSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.system_binaries import (
    BashBinary,
    BinaryNotFoundError,
    BinaryPathRequest,
    BinaryPaths,
)
from pants.engine.addresses import Address
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    CreateDigest,
    Digest,
    Directory,
    MergeDigests,
    Snapshot,
)
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    GeneratedSources,
    GenerateSourcesRequest,
    SourcesField,
    Target,
    TransitiveTargets,
    TransitiveTargetsRequest,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class GenerateFilesFromShellCommandRequest(GenerateSourcesRequest):
    input = ShellCommandSourcesField
    output = FileSourceField


@dataclass(frozen=True)
class ShellCommandProcessRequest:
    target: Target


class RunShellCommand(RunFieldSet):
    required_fields = (
        ShellCommandCommandField,
        ShellCommandRunWorkdirField,
    )


@rule(desc="Running shell command", level=LogLevel.DEBUG)
async def run_shell_command(
    request: GenerateFilesFromShellCommandRequest,
) -> GeneratedSources:
    shell_command = request.protocol_target
    result = await Get(ProcessResult, ShellCommandProcessRequest(shell_command))

    if shell_command[ShellCommandLogOutputField].value:
        if result.stdout:
            logger.info(result.stdout.decode())
        if result.stderr:
            logger.warning(result.stderr.decode())

    working_directory = shell_command.address.spec_path
    output = await Get(Snapshot, AddPrefix(result.output_digest, working_directory))
    return GeneratedSources(output)


def _shell_tool_safe_env_name(tool_name: str) -> str:
    """Replace any characters not suitable in an environment variable name with `_`."""
    return re.sub(r"\W", "_", tool_name)


@rule
async def prepare_shell_command_process(
    request: ShellCommandProcessRequest, shell_setup: ShellSetup, bash: BashBinary
) -> Process:
    shell_command = request.target
    interactive = shell_command.has_field(ShellCommandRunWorkdirField)
    if interactive:
        working_directory = shell_command[ShellCommandRunWorkdirField].value or ""
    else:
        working_directory = shell_command.address.spec_path
    command = shell_command[ShellCommandCommandField].value
    timeout = shell_command.get(ShellCommandTimeoutField).value
    tools = shell_command.get(ShellCommandToolsField, default_raw_value=()).value
    outputs = shell_command.get(ShellCommandOutputsField).value or ()

    if not command:
        raise ValueError(
            f"Missing `command` line in `{shell_command.alias}` target {shell_command.address}."
        )

    if interactive:
        command_env = {
            "CHROOT": "{chroot}",
        }
    else:
        if not tools:
            raise ValueError(
                f"Must provide any `tools` used by the `{shell_command.alias}` {shell_command.address}."
            )

        env = await Get(Environment, EnvironmentRequest(["PATH"]))
        search_path = shell_setup.executable_search_path(env)
        tool_requests = [
            BinaryPathRequest(
                binary_name=tool,
                search_path=search_path,
            )
            for tool in {*tools, *["mkdir", "ln"]}
            if tool not in BASH_BUILTIN_COMMANDS
        ]
        tool_paths = await MultiGet(
            Get(BinaryPaths, BinaryPathRequest, request) for request in tool_requests
        )

        command_env = {
            "TOOLS": " ".join(
                _shell_tool_safe_env_name(tool.binary_name) for tool in tool_requests
            ),
        }

        for binary, tool_request in zip(tool_paths, tool_requests):
            if binary.first_path:
                command_env[
                    _shell_tool_safe_env_name(tool_request.binary_name)
                ] = binary.first_path.path
            else:
                raise BinaryNotFoundError.from_request(
                    tool_request,
                    rationale=f"execute `{shell_command.alias}` {shell_command.address}",
                )

    transitive_targets = await Get(
        TransitiveTargets,
        TransitiveTargetsRequest([shell_command.address]),
    )

    sources, pkgs_per_target = await MultiGet(
        Get(
            SourceFiles,
            SourceFilesRequest(
                sources_fields=[tgt.get(SourcesField) for tgt in transitive_targets.dependencies],
                for_sources_types=(SourcesField, FileSourceField),
                enable_codegen=True,
            ),
        ),
        Get(
            FieldSetsPerTarget,
            FieldSetsPerTargetRequest(PackageFieldSet, transitive_targets.dependencies),
        ),
    )

    packages = await MultiGet(
        Get(BuiltPackage, PackageFieldSet, field_set) for field_set in pkgs_per_target.field_sets
    )

    if interactive or not working_directory or working_directory in sources.snapshot.dirs:
        work_dir = EMPTY_DIGEST
    else:
        work_dir = await Get(Digest, CreateDigest([Directory(working_directory)]))

    input_digest = await Get(
        Digest, MergeDigests([sources.snapshot.digest, work_dir, *(pkg.digest for pkg in packages)])
    )

    output_files = [f for f in outputs if not f.endswith("/")]
    output_directories = [d for d in outputs if d.endswith("/")]

    if interactive:
        relpath = os.path.relpath(
            working_directory or ".", start="/" if os.path.isabs(working_directory) else "."
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

    return Process(
        argv=(bash.path, "-c", boot_script + command),
        description=f"Running {shell_command.alias} {shell_command.address}",
        env=command_env,
        input_digest=input_digest,
        output_directories=output_directories,
        output_files=output_files,
        timeout_seconds=timeout,
        working_directory=working_directory,
    )


@rule
async def run_shell_command_request(shell_command: RunShellCommand) -> RunRequest:
    wrapped_tgt = await Get(WrappedTarget, Address, shell_command.address)
    process = await Get(Process, ShellCommandProcessRequest(wrapped_tgt.target))
    return RunRequest(
        digest=process.input_digest,
        args=process.argv,
        extra_env=process.env,
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(GenerateSourcesRequest, GenerateFilesFromShellCommandRequest),
        UnionRule(RunFieldSet, RunShellCommand),
    ]
