# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import dataclasses
import logging
import os
import shlex
from dataclasses import dataclass
from textwrap import dedent  # noqa: PNT20
from typing import Dict, Iterable, Mapping, Sequence, TypeVar, Union

from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage, EnvironmentAwarePackageRequest, PackageFieldSet
from pants.core.goals.run import RunFieldSet, RunInSandboxRequest
from pants.core.target_types import FileSourceField
from pants.core.util_rules.environments import EnvironmentNameRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.system_binaries import BashBinary
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.environment import EnvironmentName
from pants.engine.fs import (
    EMPTY_DIGEST,
    CreateDigest,
    Digest,
    Directory,
    FileContent,
    MergeDigests,
    Snapshot,
)
from pants.engine.internals.native_engine import AddressInput, RemovePrefix
from pants.engine.process import FallibleProcessResult, Process, ProcessResult, ProductDescription
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    SourcesField,
    Target,
    Targets,
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
    capture_stdout_file: str | None
    capture_stderr_file: str | None


@dataclass(frozen=True)
class AdhocProcessResult:
    process_result: ProcessResult
    adjusted_digest: Digest


@dataclass(frozen=True)
class ResolveExecutionDependenciesRequest:
    address: Address
    execution_dependencies: tuple[str, ...] | None
    runnable_dependencies: tuple[str, ...] | None


@dataclass(frozen=True)
class ResolvedExecutionDependencies:
    digest: Digest
    runnable_dependencies: RunnableDependencies | None


@dataclass(frozen=True)
class RunnableDependencies:
    path_component: str
    immutable_input_digests: Mapping[str, Digest]
    append_only_caches: Mapping[str, str]
    extra_env: Mapping[str, str]


@dataclass(frozen=True)
class ToolRunnerRequest:
    runnable_address_str: str
    args: tuple[str, ...]
    execution_dependencies: tuple[str, ...]
    runnable_dependencies: tuple[str, ...]
    target: Target
    named_caches: FrozenDict[str, str] | None = None


@dataclass(frozen=True)
class ToolRunner:
    digest: Digest
    args: tuple[str, ...]
    extra_env: FrozenDict[str, str]
    append_only_caches: FrozenDict[str, str]
    immutable_input_digests: FrozenDict[str, Digest]


#
# Things that need a home
#


@dataclass(frozen=True)
class ExtraSandboxContents:
    digest: Digest
    path: str | None
    immutable_input_digests: Mapping[str, Digest]
    append_only_caches: Mapping[str, str]
    extra_env: Mapping[str, str]


@dataclass(frozen=True)
class MergeExtraSandboxContents:
    additions: tuple[ExtraSandboxContents, ...]


@dataclass(frozen=True)
class AddExtraSandboxContentsToProcess:
    process: Process
    contents: ExtraSandboxContents


@rule
async def merge_extra_sandbox_contents(request: MergeExtraSandboxContents) -> ExtraSandboxContents:
    additions = request.additions

    digests = []
    paths = []
    immutable_input_digests: dict[str, Digest] = {}
    append_only_caches: dict[str, str] = {}
    extra_env: dict[str, str] = {}

    for addition in additions:
        digests.append(addition.digest)
        if addition.path is not None:
            paths.append(addition.path)
        _safe_update(immutable_input_digests, addition.immutable_input_digests)
        _safe_update(append_only_caches, addition.append_only_caches)
        _safe_update(extra_env, addition.extra_env)

    digest = await Get(Digest, MergeDigests(digests))
    path = ":".join(paths) if paths else None

    return ExtraSandboxContents(
        digest,
        path,
        FrozenDict(immutable_input_digests),
        FrozenDict(append_only_caches),
        FrozenDict(extra_env),
    )


@rule
async def add_extra_contents_to_prcess(request: AddExtraSandboxContentsToProcess) -> Process:
    proc = request.process
    extras = request.contents
    new_digest = await Get(
        Digest, MergeDigests((request.process.input_digest, request.contents.digest))
    )
    immutable_input_digests = dict(proc.immutable_input_digests)
    append_only_caches = dict(proc.append_only_caches)
    env = dict(proc.env)

    _safe_update(immutable_input_digests, extras.immutable_input_digests)
    _safe_update(append_only_caches, extras.append_only_caches)
    _safe_update(env, extras.extra_env)
    # need to do `PATH` after `env` in case `extra_env` contains a `PATH`.
    if extras.path:
        env["PATH"] = extras.path + (":" + env["PATH"]) if "PATH" in env else ""

    return dataclasses.replace(
        proc,
        input_digest=new_digest,
        immutable_input_digests=FrozenDict(immutable_input_digests),
        append_only_caches=FrozenDict(append_only_caches),
        env=FrozenDict(env),
    )


#
# END THINGS THAT NEED A HOME
#


async def _resolve_runnable_dependencies(
    bash: BashBinary, deps: tuple[str, ...] | None, owning: Address, origin: str
) -> tuple[Digest, RunnableDependencies | None]:
    if not deps:
        return EMPTY_DIGEST, None

    addresses = await Get(
        Addresses,
        UnparsedAddressInputs(
            (dep for dep in deps),
            owning_address=owning,
            description_of_origin=origin,
        ),
    )

    targets = await Get(Targets, Addresses, addresses)

    fspt = await Get(
        FieldSetsPerTarget,
        FieldSetsPerTargetRequest(RunFieldSet, targets),
    )

    # stores extra_env_vars from system binaries to be passed on to the adhoc_tool
    runnable_extra_env_vars_unresolved: Sequence[str] = []

    for address, field_set in zip(addresses, fspt.collection):
        if field_set:
            if field_set[0].extra_env_vars.value:
                runnable_extra_env_vars_unresolved += field_set[0].extra_env_vars.value
        else:
            raise ValueError(
                dedent(
                    f"""\
                    Address `{address.spec}` was specified as a runnable dependency, but is not
                    runnable.
                    """
                )
            )

    runnable_extra_env_vars: Dict[str, str] = {}
    if runnable_extra_env_vars_unresolved:
        runnable_extra_env_vars_resolved = await Get(
            EnvironmentVars, EnvironmentVarsRequest(runnable_extra_env_vars_unresolved)
        )
        runnable_extra_env_vars = dict(runnable_extra_env_vars_resolved)

    runnables = await MultiGet(
        Get(RunInSandboxRequest, RunFieldSet, field_set[0]) for field_set in fspt.collection
    )

    shims: list[FileContent] = []
    extras: list[ExtraSandboxContents] = []

    for address, runnable in zip(addresses, runnables):
        extras.append(
            ExtraSandboxContents(
                digest=runnable.digest,
                path=None,
                immutable_input_digests=FrozenDict(runnable.immutable_input_digests or {}),
                append_only_caches=FrozenDict(runnable.append_only_caches or {}),
                extra_env=FrozenDict(),
            )
        )
        shims.append(
            FileContent(
                address.target_name,
                _runnable_dependency_shim(bash.path, runnable.args, runnable.extra_env),
                is_executable=True,
            )
        )

    merged_extras, shim_digest = await MultiGet(
        Get(ExtraSandboxContents, MergeExtraSandboxContents(tuple(extras))),
        Get(Digest, CreateDigest(shims)),
    )

    shim_digest_path = f"_runnable_dependency_shims_{shim_digest.fingerprint}"
    immutable_input_digests = {shim_digest_path: shim_digest}
    _safe_update(immutable_input_digests, merged_extras.immutable_input_digests)
    environment = runnable_extra_env_vars
    environment["_PANTS_SHIM_ROOT"] = "{chroot}"

    return (
        merged_extras.digest,
        RunnableDependencies(
            shim_digest_path,
            FrozenDict(immutable_input_digests),
            merged_extras.append_only_caches,
            FrozenDict(environment),
        ),
    )


@rule
async def resolve_execution_environment(
    request: ResolveExecutionDependenciesRequest,
    bash: BashBinary,
) -> ResolvedExecutionDependencies:
    target_address = request.address
    raw_execution_dependencies = request.execution_dependencies

    # Always include the execution dependencies that were specified
    if raw_execution_dependencies is not None:
        _descr = f"the `execution_dependencies` from the target {target_address}"
        execution_dependencies = await Get(
            Addresses,
            UnparsedAddressInputs(
                raw_execution_dependencies,
                owning_address=target_address,
                description_of_origin=_descr,
            ),
        )
    else:
        execution_dependencies = Addresses(())

    transitive = await Get(
        TransitiveTargets,
        TransitiveTargetsRequest(execution_dependencies),
    )

    all_dependencies = (
        *(i for i in transitive.roots if i.address is not target_address),
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

    _descr = f"the `runnable_dependencies` from the target {target_address}"
    runnables_digest, runnable_dependencies = await _resolve_runnable_dependencies(
        bash, request.runnable_dependencies, target_address, _descr
    )

    dependencies_digest = await Get(
        Digest,
        MergeDigests(
            [sources.snapshot.digest, runnables_digest, *(pkg.digest for pkg in packages)]
        ),
    )

    return ResolvedExecutionDependencies(dependencies_digest, runnable_dependencies)


K = TypeVar("K")
V = TypeVar("V")


def _safe_update(d1: dict[K, V], d2: Mapping[K, V]) -> dict[K, V]:
    """Updates `d1` with the values from `d2`, raising an exception if a key exists in both
    dictionaries, but with a different value."""

    for k, v in d2.items():
        if k in d1 and d1[k] != v:
            raise ValueError(f"Key {k} was specified in both dictionaries with different values.")
        d1[k] = v
    return d1


def _runnable_dependency_shim(
    bash: str, args: Iterable[str], extra_env: Mapping[str, str]
) -> bytes:
    """The binary shim script to be placed in the output directory for the digest."""

    def _quote(s: str) -> str:
        quoted = shlex.quote(s)
        return quoted.replace("{chroot}", "'${_PANTS_SHIM_ROOT}'")

    binary = " ".join(_quote(arg) for arg in args)
    env_str = "\n".join(
        f"export {shlex.quote(key)}={_quote(value)}" for (key, value) in extra_env.items()
    )
    return dedent(
        f"""\
        #!{bash}
        {env_str}
        exec {binary} "$@"
        """
    ).encode()


@rule
async def create_tool_runner(
    request: ToolRunnerRequest,
) -> ToolRunner:
    runnable_address = await Get(
        Address,
        AddressInput,
        AddressInput.parse(
            request.runnable_address_str,
            relative_to=request.target.address.spec_path,
            description_of_origin=f"Runnable target for {request.target.address.spec_path}",
        ),
    )

    addresses = Addresses((runnable_address,))
    addresses.expect_single()

    runnable_targets = await Get(Targets, Addresses, addresses)

    run_field_sets, environment_name, execution_environment = await MultiGet(
        Get(FieldSetsPerTarget, FieldSetsPerTargetRequest(RunFieldSet, runnable_targets)),
        Get(
            EnvironmentName,
            EnvironmentNameRequest,
            EnvironmentNameRequest.from_target(request.target),
        ),
        Get(
            ResolvedExecutionDependencies,
            ResolveExecutionDependenciesRequest(
                address=runnable_address,
                execution_dependencies=request.execution_dependencies,
                runnable_dependencies=request.runnable_dependencies,
            ),
        ),
    )

    run_field_set: RunFieldSet = run_field_sets.field_sets[0]

    # Must be run in target environment so that the binaries/envvars match the execution
    # environment when we actually run the process.
    run_request = await Get(
        RunInSandboxRequest, {environment_name: EnvironmentName, run_field_set: RunFieldSet}
    )

    dependencies_digest = execution_environment.digest
    runnable_dependencies = execution_environment.runnable_dependencies

    extra_env: dict[str, str] = dict(run_request.extra_env or {})
    extra_path = extra_env.pop("PATH", None)

    extra_sandbox_contents = []

    extra_sandbox_contents.append(
        ExtraSandboxContents(
            EMPTY_DIGEST,
            extra_path,
            run_request.immutable_input_digests or FrozenDict(),
            run_request.append_only_caches or FrozenDict(),
            run_request.extra_env or FrozenDict(),
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

    merged_extras, main_digest = await MultiGet(
        Get(ExtraSandboxContents, MergeExtraSandboxContents(tuple(extra_sandbox_contents))),
        Get(Digest, MergeDigests((dependencies_digest, run_request.digest))),
    )

    extra_env = dict(merged_extras.extra_env)
    if merged_extras.path:
        extra_env["PATH"] = merged_extras.path

    append_only_caches = {
        **merged_extras.append_only_caches,
        **(request.named_caches or {}),
    }

    return ToolRunner(
        digest=main_digest,
        args=run_request.args + tuple(request.args),
        extra_env=FrozenDict(extra_env),
        append_only_caches=FrozenDict(append_only_caches),
        immutable_input_digests=FrozenDict(merged_extras.immutable_input_digests),
    )


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

    working_directory = parse_relative_directory(request.working_directory, request.address)
    root_output_directory = parse_relative_directory(
        request.root_output_directory, working_directory
    )

    extras = (
        (request.capture_stdout_file, result.stdout),
        (request.capture_stderr_file, result.stderr),
    )
    extra_contents = {i: j for i, j in extras if i}

    output_digest = result.output_digest

    if extra_contents:
        extra_digest = await Get(
            Digest,
            CreateDigest(
                FileContent(_parse_relative_file(name, working_directory), content)
                for name, content in extra_contents.items()
            ),
        )
        output_digest = await Get(Digest, MergeDigests((output_digest, extra_digest)))

    adjusted = await Get(Digest, RemovePrefix(output_digest, root_output_directory))

    return AdhocProcessResult(result, adjusted)


@rule
async def prepare_adhoc_process(
    request: AdhocProcessRequest,
    bash: BashBinary,
) -> Process:
    # currently only used directly by `experimental_test_shell_command`

    description = request.description
    address = request.address
    working_directory = parse_relative_directory(request.working_directory or "", address)
    argv = request.argv
    timeout: int | None = request.timeout
    output_files = request.output_files
    output_directories = request.output_directories
    fetch_env_vars = request.fetch_env_vars
    supplied_env_vars = request.supplied_env_var_values or FrozenDict()
    append_only_caches = request.append_only_caches or FrozenDict()
    immutable_input_digests = request.immutable_input_digests or FrozenDict()

    command_env: dict[str, str] = {}

    # env vars may come from 2 sources:
    # 1. system_binary parameter extra_env_vars, coming in from runnable_dependencies
    # 2. adhoc_tool parameter extra_env vars
    # below logic handles 1. first, so 2. can override
    if supplied_env_vars:
        command_env.update(supplied_env_vars)

    extra_env = await Get(EnvironmentVars, EnvironmentVarsRequest(fetch_env_vars))
    command_env.update(extra_env)

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


def parse_relative_directory(workdir_in: str, relative_to: Union[Address, str]) -> str:
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


def _parse_relative_file(file_in: str, relative_to: str) -> str:
    """Convert the `capture_std..._file` fields into something that can be understood by
    `Process`."""

    if file_in.startswith("/"):
        return file_in[1:]

    return os.path.join(relative_to, file_in)


def rules():
    return collect_rules()
