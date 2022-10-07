# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.build_files.fmt.buildifier.subsystem import Buildifier
from pants.core.goals.fmt import FmtFilesRequest, FmtResult, Partitions
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.engine.internals.build_files import BuildFileOptions
from pants.engine.internals.native_engine import Digest, MergeDigests, Snapshot
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.source.filespec import FilespecMatcher
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


class BuildifierRequest(FmtFilesRequest):
    tool_subsystem = Buildifier


@rule
async def partition_build_files(
    request: BuildifierRequest.PartitionRequest,
    buildifier: Buildifier,
    build_file_options: BuildFileOptions,
) -> Partitions:
    if buildifier.skip:
        return Partitions()

    specified_build_files = FilespecMatcher(
        includes=[os.path.join("**", p) for p in build_file_options.patterns],
        excludes=build_file_options.ignores,
    ).matches(request.files)

    return Partitions.single_partition(specified_build_files)


@rule(desc="Format with Buildifier", level=LogLevel.DEBUG)
async def buildfier_fmt(
    request: BuildifierRequest.SubPartition, buildifier: Buildifier, platform: Platform
) -> FmtResult:
    buildifier_tool = await Get(
        DownloadedExternalTool, ExternalToolRequest, buildifier.get_request(platform)
    )
    input_digest = await Get(
        Digest,
        MergeDigests((request.snapshot.digest, buildifier_tool.digest)),
    )
    result = await Get(
        ProcessResult,
        Process(
            argv=[buildifier_tool.exe, "-type=build", *request.files],
            input_digest=input_digest,
            output_files=request.files,
            description=f"Run buildifier on {pluralize(len(request.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    output_snapshot = await Get(Snapshot, Digest, result.output_digest)
    return FmtResult.create(
        result, request.snapshot, output_snapshot, formatter_name=BuildifierRequest.tool_name
    )


def rules():
    return [
        *collect_rules(),
        *BuildifierRequest.rules(),
    ]
