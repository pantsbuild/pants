# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.build_files.fmt.base import FmtBuildFilesRequest
from pants.backend.build_files.fmt.buildifier.subsystem import Buildifier
from pants.core.goals.fmt import AbstractFmtRequest, FmtResult
from pants.core.util_rules.external_tool import download_external_tool
from pants.engine.internals.native_engine import MergeDigests
from pants.engine.intrinsics import merge_digests_request_to_digest
from pants.engine.platform import Platform
from pants.engine.process import Process, fallible_to_exec_result_or_raise
from pants.engine.rules import collect_rules, implicitly, rule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


class BuildifierRequest(FmtBuildFilesRequest):
    tool_subsystem = Buildifier


async def _run_buildifier_fmt(
    request: AbstractFmtRequest.Batch, buildifier: Buildifier, platform: Platform
) -> FmtResult:
    buildifier_tool = await download_external_tool(buildifier.get_request(platform))
    input_digest = await merge_digests_request_to_digest(
        MergeDigests((request.snapshot.digest, buildifier_tool.digest))
    )
    result = await fallible_to_exec_result_or_raise(
        **implicitly(
            Process(
                argv=[buildifier_tool.exe, "-type=build", *request.files],
                input_digest=input_digest,
                output_files=request.files,
                description=f"Run {Buildifier.options_scope} on {pluralize(len(request.files), 'file')}.",
                level=LogLevel.DEBUG,
            )
        ),
    )
    return await FmtResult.create(request, result)


@rule(desc="Format with Buildifier", level=LogLevel.DEBUG)
async def buildifier_fmt(
    request: BuildifierRequest.Batch, buildifier: Buildifier, platform: Platform
) -> FmtResult:
    result = await _run_buildifier_fmt(request, buildifier, platform)
    return result


def rules():
    return [
        *collect_rules(),
        *BuildifierRequest.rules(),
    ]
