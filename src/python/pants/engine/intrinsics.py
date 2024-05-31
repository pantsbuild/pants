# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

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
    Paths,
    RemovePrefix,
    Snapshot,
)
from pants.engine.internals import native_engine
from pants.engine.internals.docker import DockerResolveImageRequest, DockerResolveImageResult
from pants.engine.internals.native_dep_inference import (
    NativeParsedJavascriptDependencies,
    NativeParsedPythonDependencies,
)
from pants.engine.internals.native_engine import NativeDependenciesRequest
from pants.engine.internals.session import RunId, SessionValues
from pants.engine.process import (
    FallibleProcessResult,
    InteractiveProcess,
    InteractiveProcessResult,
    Process,
    ProcessExecutionEnvironment,
)
from pants.engine.rules import _uncacheable_rule, collect_rules, rule


@rule
async def create_digest_to_digest(
    create_digest: CreateDigest,
) -> Digest:
    return await native_engine.create_digest_to_digest(create_digest)


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
async def download_file_to_digest(
    native_download_file: NativeDownloadFile,
) -> Digest:
    return await native_engine.download_file_to_digest(native_download_file)


@rule
async def digest_to_snapshot(digest: Digest) -> Snapshot:
    return await native_engine.digest_to_snapshot(digest)


@rule
async def directory_digest_to_digest_contents(digest: Digest) -> DigestContents:
    return await native_engine.directory_digest_to_digest_contents(digest)


@rule
async def directory_digest_to_digest_entries(digest: Digest) -> DigestEntries:
    return await native_engine.directory_digest_to_digest_entries(digest)


@rule
async def merge_digests_request_to_digest(merge_digests: MergeDigests) -> Digest:
    return await native_engine.merge_digests_request_to_digest(merge_digests)


@rule
async def remove_prefix_request_to_digest(remove_prefix: RemovePrefix) -> Digest:
    return await native_engine.remove_prefix_request_to_digest(remove_prefix)


@rule
async def add_prefix_request_to_digest(add_prefix: AddPrefix) -> Digest:
    return await native_engine.add_prefix_request_to_digest(add_prefix)


@rule
async def process_request_to_process_result(
    process: Process, process_execution_environment: ProcessExecutionEnvironment
) -> FallibleProcessResult:
    return await native_engine.process_request_to_process_result(
        process, process_execution_environment
    )


@rule
async def digest_subset_to_digest(digest_subset: DigestSubset) -> Digest:
    return await native_engine.digest_subset_to_digest(digest_subset)


@rule
async def session_values() -> SessionValues:
    return await native_engine.session_values()


@rule
async def run_id() -> RunId:
    return await native_engine.run_id()


@_uncacheable_rule
async def interactive_process(
    process: InteractiveProcess, process_execution_environment: ProcessExecutionEnvironment
) -> InteractiveProcessResult:
    return await native_engine.interactive_process(process, process_execution_environment)


@rule
async def docker_resolve_image(request: DockerResolveImageRequest) -> DockerResolveImageResult:
    return await native_engine.docker_resolve_image(request)


@rule
async def parse_python_deps(
    deps_request: NativeDependenciesRequest,
) -> NativeParsedPythonDependencies:
    return await native_engine.parse_python_deps(deps_request)


@rule
async def parse_javascript_deps(
    deps_request: NativeDependenciesRequest,
) -> NativeParsedJavascriptDependencies:
    return await native_engine.parse_javascript_deps(deps_request)


def rules():
    return [
        *collect_rules(),
    ]
