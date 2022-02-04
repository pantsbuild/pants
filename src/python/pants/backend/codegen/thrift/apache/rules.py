# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.codegen.thrift.apache.subsystem import ApacheThriftSubsystem
from pants.backend.codegen.thrift.target_types import ThriftSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.fs import CreateDigest, Digest, Directory, MergeDigests, RemovePrefix, Snapshot
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import (
    BinaryNotFoundError,
    BinaryPathRequest,
    BinaryPaths,
    BinaryPathTest,
    Process,
    ProcessCacheScope,
    ProcessResult,
)
from pants.engine.rules import collect_rules, rule
from pants.engine.target import TransitiveTargets, TransitiveTargetsRequest
from pants.source.source_root import SourceRootsRequest, SourceRootsResult
from pants.util.logging import LogLevel
from pants.util.strutil import bullet_list

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GenerateThriftSourcesRequest:
    thrift_source_field: ThriftSourceField
    lang_id: str
    lang_options: tuple[str, ...]
    lang_name: str


@dataclass(frozen=True)
class GeneratedThriftSources:
    snapshot: Snapshot


@dataclass(frozen=True)
class ApacheThriftSetup:
    path: str


@rule
async def generate_apache_thrift_sources(
    request: GenerateThriftSourcesRequest,
    thrift: ApacheThriftSetup,
) -> GeneratedThriftSources:
    output_dir = "_generated_files"

    transitive_targets, empty_output_dir_digest = await MultiGet(
        Get(TransitiveTargets, TransitiveTargetsRequest([request.thrift_source_field.address])),
        Get(Digest, CreateDigest([Directory(output_dir)])),
    )

    transitive_sources, target_sources = await MultiGet(
        Get(
            SourceFiles,
            SourceFilesRequest(
                tgt[ThriftSourceField]
                for tgt in transitive_targets.closure
                if tgt.has_field(ThriftSourceField)
            ),
        ),
        Get(SourceFiles, SourceFilesRequest([request.thrift_source_field])),
    )

    sources_roots = await Get(
        SourceRootsResult,
        SourceRootsRequest,
        SourceRootsRequest.for_files(transitive_sources.snapshot.files),
    )
    deduped_source_root_paths = sorted({sr.path for sr in sources_roots.path_to_root.values()})

    input_digest = await Get(
        Digest,
        MergeDigests(
            [
                transitive_sources.snapshot.digest,
                target_sources.snapshot.digest,
                empty_output_dir_digest,
            ]
        ),
    )

    options_str = ""
    if request.lang_options:
        options_str = f":{','.join(opt for opt in request.lang_options)}"

    maybe_include_paths = []
    for path in deduped_source_root_paths:
        maybe_include_paths.extend(["-I", path])

    args = [
        thrift.path,
        "-out",
        output_dir,
        *maybe_include_paths,
        "--gen",
        f"{request.lang_id}{options_str}",
        *target_sources.snapshot.files,
    ]

    result = await Get(
        ProcessResult,
        Process(
            args,
            input_digest=input_digest,
            output_directories=(output_dir,),
            description=f"Generating {request.lang_name} sources from {request.thrift_source_field.address}.",
            level=LogLevel.DEBUG,
        ),
    )

    output_snapshot = await Get(Snapshot, RemovePrefix(result.output_digest, output_dir))
    return GeneratedThriftSources(output_snapshot)


@rule
async def setup_thrift_tool(apache_thrift: ApacheThriftSubsystem) -> ApacheThriftSetup:
    env = await Get(Environment, EnvironmentRequest(["PATH"]))
    search_paths = apache_thrift.thrift_search_paths(env)
    all_thrift_binary_paths = await Get(
        BinaryPaths,
        BinaryPathRequest(
            search_path=search_paths,
            binary_name="thrift",
            test=BinaryPathTest(["-version"]),
        ),
    )
    if not all_thrift_binary_paths.paths:
        raise BinaryNotFoundError(
            "Cannot find any `thrift` binaries using the option "
            f"`[apache-thrift].thrift_search_paths`: {list(search_paths)}\n\n"
            "To fix, please install Apache Thrift (https://thrift.apache.org/) with the version "
            f"{apache_thrift.expected_version} (set by `[apache-thrift].expected_version`) and ensure "
            "that it is discoverable via `[apache-thrift].thrift_search_paths`."
        )

    version_results = await MultiGet(
        Get(
            ProcessResult,
            Process(
                (binary_path.path, "-version"),
                description=f"Determine Apache Thrift version for {binary_path.path}",
                level=LogLevel.DEBUG,
                cache_scope=ProcessCacheScope.PER_RESTART_SUCCESSFUL,
            ),
        )
        for binary_path in all_thrift_binary_paths.paths
    )

    invalid_versions = []
    for binary_path, version_result in zip(all_thrift_binary_paths.paths, version_results):
        try:
            _raw_version = version_result.stdout.decode("utf-8").split()[2]
            _version_components = _raw_version.split(".")  # e.g. [1, 17] or [1, 17, 1]
            version = f"{_version_components[0]}.{_version_components[1]}"
        except IndexError:
            raise AssertionError(
                f"Failed to parse `thrift -version` output for {binary_path}. Please open a bug at "
                f"https://github.com/pantsbuild/pants/issues/new/choose with the below data:"
                f"\n\n"
                f"{version_result}"
            )

        if version == apache_thrift.expected_version:
            return ApacheThriftSetup(binary_path.path)

        logger.debug(
            f"The Thrift binary at {binary_path.path} has version {version}, but this "
            f"project is using {apache_thrift.expected_version} "
            "(set by `[apache-thrift].expected_version`). Ignoring."
        )
        invalid_versions.append((binary_path.path, version))

    invalid_versions_str = bullet_list(
        f"{path}: {version}" for path, version in sorted(invalid_versions)
    )
    raise BinaryNotFoundError(
        "Cannot find a `thrift` binary with the expected version of "
        f"{apache_thrift.expected_version} (set by `[apache-thrift].expected_version`).\n\n"
        f"Found these `thrift` binaries, but they had different versions:\n\n"
        f"{invalid_versions_str}\n\n"
        "To fix, please install the expected version (https://thrift.apache.org/) and ensure "
        "that it is discoverable via the option `[apache-thrift].thrift_search_paths`, or change "
        "`[apache-thrift].expected_version`."
    )


def rules():
    return collect_rules()
