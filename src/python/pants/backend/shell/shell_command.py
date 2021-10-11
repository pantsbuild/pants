# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import shlex
from textwrap import dedent

from pants.backend.shell.builtin import BASH_BUILTIN_COMMANDS
from pants.backend.shell.shell_setup import ShellSetup
from pants.backend.shell.target_types import (
    ShellCommandCommandField,
    ShellCommandLogOutputField,
    ShellCommandOutputsField,
    ShellCommandSourcesField,
    ShellCommandTimeout,
    ShellCommandToolsField,
)
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.target_types import FileSourcesField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
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
from pants.engine.process import (
    BashBinary,
    BinaryNotFoundError,
    BinaryPathRequest,
    BinaryPaths,
    Process,
    ProcessResult,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    GeneratedSources,
    GenerateSourcesRequest,
    SourcesField,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class GenerateFilesFromShellCommandRequest(GenerateSourcesRequest):
    input = ShellCommandSourcesField
    output = FileSourcesField


@rule(desc="Running experimental_shell_command", level=LogLevel.DEBUG)
async def run_shell_command(
    request: GenerateFilesFromShellCommandRequest,
    shell_setup: ShellSetup,
    bash: BashBinary,
) -> GeneratedSources:
    shell_command = request.protocol_target
    working_directory = shell_command.address.spec_path
    command = shell_command[ShellCommandCommandField].value
    timeout = shell_command[ShellCommandTimeout].value
    tools = shell_command[ShellCommandToolsField].value
    outputs = shell_command[ShellCommandOutputsField].value or ()

    if not command:
        raise ValueError(
            f"Missing `command` line in `shell_command` target {shell_command.address}."
        )

    if not tools:
        raise ValueError(
            f"Must provide any `tools` used by the `shell_command` {shell_command.address}."
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
        "TOOLS": " ".join(shlex.quote(tool.binary_name) for tool in tool_requests),
    }

    for binary, tool_request in zip(tool_paths, tool_requests):
        if binary.first_path:
            command_env[tool_request.binary_name] = binary.first_path.path
        else:
            raise BinaryNotFoundError.from_request(
                tool_request,
                rationale=f"execute experimental_shell_command {shell_command.address}",
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
                for_sources_types=(SourcesField, FileSourcesField),
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

    if working_directory in sources.snapshot.dirs:
        work_dir = EMPTY_DIGEST
    else:
        work_dir = await Get(Digest, CreateDigest([Directory(working_directory)]))

    input_digest = await Get(
        Digest, MergeDigests([sources.snapshot.digest, work_dir, *(pkg.digest for pkg in packages)])
    )

    output_files = [f for f in outputs if not f.endswith("/")]
    output_directories = [d for d in outputs if d.endswith("/")]

    # Setup bin_relpath dir with symlinks to all requested tools, so that we can use PATH.
    bin_relpath = ".bin"
    setup_tool_symlinks_script = ";".join(
        dedent(
            f"""\
            $mkdir -p {bin_relpath}
            for tool in $TOOLS; do $ln -s ${{!tool}} {bin_relpath}/; done
            export PATH="$PWD/{bin_relpath}"
            """
        ).split("\n")
    )

    result = await Get(
        ProcessResult,
        Process(
            argv=(bash.path, "-c", setup_tool_symlinks_script + command),
            description=f"Running experimental_shell_command {shell_command.address}",
            env=command_env,
            input_digest=input_digest,
            output_directories=output_directories,
            output_files=output_files,
            timeout_seconds=timeout,
            working_directory=working_directory,
        ),
    )

    if shell_command[ShellCommandLogOutputField].value:
        if result.stdout:
            logger.info(result.stdout.decode())
        if result.stderr:
            logger.warning(result.stderr.decode())

    output = await Get(Snapshot, AddPrefix(result.output_digest, working_directory))
    return GeneratedSources(output)


def rules():
    return [
        *collect_rules(),
        UnionRule(GenerateSourcesRequest, GenerateFilesFromShellCommandRequest),
    ]
