# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.build_files.fmt.base import FmtBuildFilesRequest
from pants.backend.build_files.fmt.buildifier.subsystem import Buildifier
from pants.core.goals.fmt import FmtResult
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


class BuildifierRequest(FmtBuildFilesRequest):
    tool_subsystem = Buildifier


@rule(desc="Format with Buildifier", level=LogLevel.DEBUG)
async def buildfier_fmt(
    request: BuildifierRequest.Batch, buildifier: Buildifier, platform: Platform
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
    return await FmtResult.create(request, result)


def rules():
    return [
        *collect_rules(),
        *BuildifierRequest.rules(),
    ]
