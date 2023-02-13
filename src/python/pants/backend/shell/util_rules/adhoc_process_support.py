# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import dataclasses
import itertools
import logging
import os
import shlex
from dataclasses import dataclass
from typing import Union

from pants.backend.shell.target_types import (
    ShellCommandExecutionDependenciesField,
    ShellCommandOutputDependenciesField,
    ShellCommandOutputDirectoriesField,
    ShellCommandOutputFilesField,
    ShellCommandOutputsField,
)
from pants.base.deprecated import warn_or_error
from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage, EnvironmentAwarePackageRequest, PackageFieldSet
from pants.core.target_types import FileSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.system_binaries import BashBinary
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Digest, Directory, MergeDigests, Snapshot
from pants.engine.internals.native_engine import RemovePrefix
from pants.engine.process import FallibleProcessResult, Process, ProcessResult, ProductDescription
from pants.engine.rules import Get, MultiGet, collect_rules, rule, rule_helper
from pants.engine.target import (
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    SourcesField,
    Target,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.util.frozendict import FrozenDict

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AdhocProcessRequest:
    description: str
    address: Address
    working_directory: str
    root_output_directory: str
    argv: tuple[str, ...]
    timeout: int | None
    input_digest: Digest
    immutable_input_digests: FrozenDict[str, Digest] | None
    append_only_caches: FrozenDict[str, str] | None
    output_files: tuple[str, ...]
    output_directories: tuple[str, ...]
    fetch_env_vars: tuple[str, ...]
    supplied_env_var_values: FrozenDict[str, str] | None
    log_on_process_errors: FrozenDict[int, str] | None
    log_output: bool


@dataclass(frozen=True)
class AdhocProcessResult:
    process_result: ProcessResult
    adjusted_digest: Digest


@rule_helper
async def _execution_environment_from_dependencies(adhoc_process_target: Target) -> Digest:

    runtime_dependencies_defined = (
        adhoc_process_target.get(ShellCommandExecutionDependenciesField).value is not None
    )

    any_dependencies_defined = (
        adhoc_process_target.get(ShellCommandOutputDependenciesField).value is not None
    )

    # If we're specifying the `dependencies` as relevant to the execution environment, then include
    # this command as a root for the transitive dependency search for execution dependencies.
    maybe_this_target = (adhoc_process_target.address,) if not runtime_dependencies_defined else ()

    # Always include the execution dependencies that were specified
    if runtime_dependencies_defined:
        runtime_dependencies = await Get(
            Addresses,
            UnparsedAddressInputs,
            adhoc_process_target.get(
                ShellCommandExecutionDependenciesField
            ).to_unparsed_address_inputs(),
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
        *(i for i in transitive.roots if i is not adhoc_process_target),
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
        Get(BuiltPackage, EnvironmentAwarePackageRequest(field_set))
        for field_set in pkgs_per_target.field_sets
    )

    dependencies_digest = await Get(
        Digest, MergeDigests([sources.snapshot.digest, *(pkg.digest for pkg in packages)])
    )

    return dependencies_digest


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
async def run_adhoc_process(
    request: AdhocProcessRequest,
) -> AdhocProcessResult:
    process = await Get(Process, AdhocProcessRequest, request)

    fallible_result = await Get(FallibleProcessResult, Process, process)

    log_on_errors = request.log_on_process_errors or FrozenDict()
    error_to_log = log_on_errors.get(fallible_result.exit_code, None)
    if error_to_log:
        logger.error(error_to_log)

    result = await Get(
        ProcessResult,
        {
            fallible_result: FallibleProcessResult,
            ProductDescription(request.description): ProductDescription,
        },
    )

    if request.log_output:
        if result.stdout:
            logger.info(result.stdout.decode())
        if result.stderr:
            logger.warning(result.stderr.decode())

    working_directory = _parse_working_directory(request.working_directory, request.address)
    root_output_directory = _parse_working_directory(
        request.root_output_directory, working_directory
    )

    adjusted = await Get(Digest, RemovePrefix(result.output_digest, root_output_directory))

    return AdhocProcessResult(result, adjusted)


@rule
async def prepare_adhoc_process(
    request: AdhocProcessRequest,
    bash: BashBinary,
) -> Process:
    # currently only used directly by `experimental_test_shell_command`

    description = request.description
    address = request.address
    working_directory = _parse_working_directory(request.working_directory or "", address)
    argv = request.argv
    timeout: int | None = request.timeout
    output_files = request.output_files
    output_directories = request.output_directories
    fetch_env_vars = request.fetch_env_vars
    supplied_env_vars = request.supplied_env_var_values or FrozenDict()
    append_only_caches = request.append_only_caches or FrozenDict()
    immutable_input_digests = request.immutable_input_digests or FrozenDict()

    command_env: dict[str, str] = {}

    extra_env = await Get(EnvironmentVars, EnvironmentVarsRequest(fetch_env_vars))
    command_env.update(extra_env)

    if supplied_env_vars:
        command_env.update(supplied_env_vars)

    input_snapshot = await Get(Snapshot, Digest, request.input_digest)

    if not working_directory or working_directory in input_snapshot.dirs:
        # Needed to ensure that underlying filesystem does not change during run
        work_dir = EMPTY_DIGEST
    else:
        work_dir = await Get(Digest, CreateDigest([Directory(working_directory)]))

    input_digest = await Get(Digest, MergeDigests([request.input_digest, work_dir]))

    proc = Process(
        argv=argv,
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

    return _output_at_build_root(proc, bash)


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


def _parse_working_directory(workdir_in: str, relative_to: Union[Address, str]) -> str:
    """Convert the `workdir` field into something that can be understood by `Process`."""

    if isinstance(relative_to, Address):
        reldir = relative_to.spec_path
    else:
        reldir = relative_to

    if workdir_in == ".":
        return reldir
    elif workdir_in.startswith("./"):
        return os.path.join(reldir, workdir_in[2:])
    elif workdir_in.startswith("/"):
        return workdir_in[1:]
    else:
        return workdir_in


def rules():
    return collect_rules()
