# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging

from pants.engine.environment import EnvironmentName
from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    DigestContents,
    DigestEntries,
    DigestSubset,
    MergeDigests,
    NativeDownloadFile,
    PathGlobs,
    PathMetadataRequest,
    PathMetadataResult,
    Paths,
    RemovePrefix,
    Snapshot,
)
from pants.engine.internals import native_engine
from pants.engine.internals.docker import DockerResolveImageRequest, DockerResolveImageResult
from pants.engine.internals.native_dep_inference import (
    NativeDockerfileInfos,
    NativeJavascriptFilesDependencies,
    NativePythonFilesDependencies,
)
from pants.engine.internals.native_engine import NativeDependenciesRequest, task_side_effected
from pants.engine.internals.session import RunId, SessionValues
from pants.engine.process import (
    FallibleProcessResult,
    InteractiveProcess,
    InteractiveProcessResult,
    Process,
    ProcessExecutionEnvironment,
    ProcessResultWithRetries,
    ProcessWithRetries,
)
from pants.engine.rules import _uncacheable_rule, collect_rules, implicitly, rule
from pants.util.docutil import git_url
from pants.util.frozendict import FrozenDict


@rule
async def create_digest(
    create_digest: CreateDigest,
) -> Digest:
    return await native_engine.create_digest(create_digest)


@rule
async def path_globs_to_digest(
    path_globs: PathGlobs,
) -> Digest:
    return await native_engine.path_globs_to_digest(path_globs)


@rule
async def path_globs_to_paths(
    path_globs: PathGlobs,
) -> Paths:
    return await native_engine.path_globs_to_paths(path_globs)


@rule
async def download_file(
    native_download_file: NativeDownloadFile,
) -> Digest:
    return await native_engine.download_file(native_download_file)


@rule
async def digest_to_snapshot(digest: Digest) -> Snapshot:
    return await native_engine.digest_to_snapshot(digest)


@rule
async def get_digest_contents(digest: Digest) -> DigestContents:
    return await native_engine.get_digest_contents(digest)


@rule
async def get_digest_entries(digest: Digest) -> DigestEntries:
    return await native_engine.get_digest_entries(digest)


@rule
async def merge_digests(merge_digests: MergeDigests) -> Digest:
    return await native_engine.merge_digests(merge_digests)


@rule
async def remove_prefix(remove_prefix: RemovePrefix) -> Digest:
    return await native_engine.remove_prefix(remove_prefix)


@rule
async def add_prefix(add_prefix: AddPrefix) -> Digest:
    return await native_engine.add_prefix(add_prefix)


@rule
async def execute_process(
    process: Process, process_execution_environment: ProcessExecutionEnvironment
) -> FallibleProcessResult:
    return await native_engine.execute_process(process, process_execution_environment)


@rule
async def execute_process_with_retry(req: ProcessWithRetries) -> ProcessResultWithRetries:
    results: list[FallibleProcessResult] = []
    for attempt in range(0, req.attempts):
        proc = dataclasses.replace(req.proc, attempt=attempt)
        result = await execute_process(  # noqa: PNT30: We only know that we need to rerun the test after we run it
            proc, **implicitly()
        )
        results.append(result)
        if result.exit_code == 0:
            break
    return ProcessResultWithRetries(tuple(results))


@rule
async def digest_subset_to_digest(digest_subset: DigestSubset) -> Digest:
    return await native_engine.digest_subset_to_digest(digest_subset)


@rule
async def session_values() -> SessionValues:
    return await native_engine.session_values()


@rule
async def run_id() -> RunId:
    return await native_engine.run_id()


__SQUELCH_WARNING = "__squelch_warning"


# NB: Call one of the helpers below, instead of calling this rule directly,
#  to ensure correct application of restartable logic.
@_uncacheable_rule
async def _interactive_process(
    process: InteractiveProcess, process_execution_environment: ProcessExecutionEnvironment
) -> InteractiveProcessResult:
    # This is a crafty way for a caller to signal into this function without a dedicated arg
    # (which would confound the solver).  Note that we go via __dict__ instead of using
    # setattr/delattr, because those error for frozen dataclasses.
    if __SQUELCH_WARNING in process.__dict__:
        del process.__dict__[__SQUELCH_WARNING]
    else:
        logging.warning(
            "A plugin is calling `await _interactive_process(...)` directly. This will cause "
            "restarting logic not to be applied. Use `await run_interactive_process(process)` "
            "or `await run_interactive_process_in_environment(process, environment_name)` instead. "
            f"See {git_url('src/python/pants/engine/intrinsics.py')} for more details."
        )
    return await native_engine.interactive_process(process, process_execution_environment)


async def run_interactive_process(process: InteractiveProcess) -> InteractiveProcessResult:
    # NB: We must call task_side_effected() in this helper, rather than in a nested @rule call,
    #  so that the Task for the @rule that calls this helper is the one marked as non-restartable.
    if not process.restartable:
        task_side_effected()

    process.__dict__[__SQUELCH_WARNING] = True
    ret: InteractiveProcessResult = await _interactive_process(process, **implicitly())
    return ret


async def run_interactive_process_in_environment(
    process: InteractiveProcess, environment_name: EnvironmentName
) -> InteractiveProcessResult:
    # NB: We must call task_side_effected() in this helper, rather than in a nested @rule call,
    #  so that the Task for the @rule that calls this helper is the one marked as non-restartable.
    if not process.restartable:
        task_side_effected()

    process.__dict__[__SQUELCH_WARNING] = True
    ret: InteractiveProcessResult = await _interactive_process(
        process, **implicitly({environment_name: EnvironmentName})
    )
    return ret


@rule
async def docker_resolve_image(request: DockerResolveImageRequest) -> DockerResolveImageResult:
    return await native_engine.docker_resolve_image(request)


@rule
async def parse_dockerfile_info(
    deps_request: NativeDependenciesRequest,
) -> NativeDockerfileInfos:
    path_infos_pairs = await native_engine.parse_dockerfile_info(deps_request)
    return NativeDockerfileInfos(FrozenDict(path_infos_pairs))


@rule
async def parse_python_deps(
    deps_request: NativeDependenciesRequest,
) -> NativePythonFilesDependencies:
    path_deps_pairs = await native_engine.parse_python_deps(deps_request)
    return NativePythonFilesDependencies(FrozenDict(path_deps_pairs))


@rule
async def parse_javascript_deps(
    deps_request: NativeDependenciesRequest,
) -> NativeJavascriptFilesDependencies:
    path_deps_pairs = await native_engine.parse_javascript_deps(deps_request)
    return NativeJavascriptFilesDependencies(FrozenDict(path_deps_pairs))


@rule
async def path_metadata_request(request: PathMetadataRequest) -> PathMetadataResult:
    return await native_engine.path_metadata_request(request)


def rules():
    return [
        *collect_rules(),
    ]
