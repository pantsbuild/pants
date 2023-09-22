# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging

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
)
from pants.build_graph.address import Address, AddressInput
from pants.core.goals.run import RunFieldSet, RunInSandboxRequest
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
from pants.engine.addresses import Addresses
from pants.engine.environment import EnvironmentName
from pants.engine.fs import Digest, MergeDigests, Snapshot
from pants.engine.internals.native_engine import EMPTY_DIGEST
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


class GenerateFilesFromAdhocToolRequest(GenerateSourcesRequest):
    input = AdhocToolSourcesField
    output = FileSourceField


@rule(desc="Running run_in_sandbox target", level=LogLevel.DEBUG)
async def run_in_sandbox_request(
    request: GenerateFilesFromAdhocToolRequest,
) -> GeneratedSources:
    target = request.protocol_target
    description = f"the `{target.alias}` at {target.address}"
    environment_name = await Get(
        EnvironmentName, EnvironmentNameRequest, EnvironmentNameRequest.from_target(target)
    )

    runnable_address_str = target[AdhocToolRunnableField].value
    if not runnable_address_str:
        raise Exception(f"Must supply a value for `runnable` for {description}.")

    runnable_address = await Get(
        Address,
        AddressInput,
        AddressInput.parse(
            runnable_address_str,
            relative_to=target.address.spec_path,
            description_of_origin=f"The `{AdhocToolRunnableField.alias}` field of {description}",
        ),
    )

    addresses = Addresses((runnable_address,))
    addresses.expect_single()

    runnable_targets = await Get(Targets, Addresses, addresses)
    field_sets = await Get(
        FieldSetsPerTarget, FieldSetsPerTargetRequest(RunFieldSet, runnable_targets)
    )
    run_field_set: RunFieldSet = field_sets.field_sets[0]

    working_directory = target[AdhocToolWorkdirField].value or ""
    root_output_directory = target[AdhocToolOutputRootDirField].value or ""

    # Must be run in target environment so that the binaries/envvars match the execution
    # environment when we actually run the process.
    run_request = await Get(
        RunInSandboxRequest, {environment_name: EnvironmentName, run_field_set: RunFieldSet}
    )

    execution_environment = await Get(
        ResolvedExecutionDependencies,
        ResolveExecutionDependenciesRequest(
            target.address,
            target.get(AdhocToolExecutionDependenciesField).value,
            target.get(AdhocToolRunnableDependenciesField).value,
        ),
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

    merged_extras = await Get(
        ExtraSandboxContents, MergeExtraSandboxContents(tuple(extra_sandbox_contents))
    )
    extra_env = dict(merged_extras.extra_env)
    if merged_extras.path:
        extra_env["PATH"] = merged_extras.path

    input_digest = await Get(Digest, MergeDigests((dependencies_digest, run_request.digest)))

    output_files = target.get(AdhocToolOutputFilesField).value or ()
    output_directories = target.get(AdhocToolOutputDirectoriesField).value or ()

    extra_args = target.get(AdhocToolArgumentsField).value or ()

    append_only_caches = {
        **merged_extras.append_only_caches,
        **target.get(AdhocToolNamedCachesField).value,
    }

    process_request = AdhocProcessRequest(
        description=description,
        address=target.address,
        working_directory=working_directory,
        root_output_directory=root_output_directory,
        argv=tuple(run_request.args + extra_args),
        timeout=None,
        input_digest=input_digest,
        immutable_input_digests=FrozenDict.frozen(merged_extras.immutable_input_digests),
        append_only_caches=FrozenDict(append_only_caches),
        output_files=output_files,
        output_directories=output_directories,
        fetch_env_vars=target.get(AdhocToolExtraEnvVarsField).value or (),
        supplied_env_var_values=FrozenDict(extra_env),
        log_on_process_errors=None,
        log_output=target[AdhocToolLogOutputField].value,
        capture_stderr_file=target[AdhocToolStderrFilenameField].value,
        capture_stdout_file=target[AdhocToolStdoutFilenameField].value,
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
