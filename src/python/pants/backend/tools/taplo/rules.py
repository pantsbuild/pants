# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Any

from pants.backend.tools.taplo.subsystem import Taplo
from pants.core.goals.fmt import FmtFilesRequest, FmtResult, Partitions
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules.config_files import find_config_file
from pants.core.util_rules.external_tool import download_external_tool
from pants.engine.fs import MergeDigests
from pants.engine.intrinsics import merge_digests
from pants.engine.platform import Platform
from pants.engine.process import Process, execute_process_or_raise
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.unions import UnionRule
from pants.source.filespec import FilespecMatcher
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


class TaploFmtRequest(FmtFilesRequest):
    tool_subsystem = Taplo


@rule
async def partition_inputs(
    request: TaploFmtRequest.PartitionRequest, taplo: Taplo
) -> Partitions[Any]:
    if taplo.skip or not request.files:
        return Partitions()

    matched_filepaths = FilespecMatcher(
        includes=[
            (glob[2:] if glob.startswith(r"\\!") else glob)
            for glob in taplo.glob_pattern
            if not glob.startswith("!")
        ],
        excludes=[glob[1:] for glob in taplo.glob_pattern if glob.startswith("!")],
    ).matches(tuple(request.files))

    return Partitions.single_partition(sorted(matched_filepaths))


@rule(desc="Format with taplo", level=LogLevel.DEBUG)
async def taplo_fmt(request: TaploFmtRequest.Batch, taplo: Taplo, platform: Platform) -> FmtResult:
    download_taplo_get = download_external_tool(taplo.get_request(platform))
    config_files_get = find_config_file(taplo.config_request())
    downloaded_taplo, config_digest = await concurrently(download_taplo_get, config_files_get)
    input_digest = await merge_digests(
        MergeDigests(
            (request.snapshot.digest, downloaded_taplo.digest, config_digest.snapshot.digest)
        )
    )

    argv = (
        downloaded_taplo.exe,
        "fmt",
        *taplo.args,
        *request.files,
    )
    result = await execute_process_or_raise(
        **implicitly(
            Process(
                argv=argv,
                input_digest=input_digest,
                output_files=request.files,
                description=f"Run taplo on {pluralize(len(request.files), 'file')}.",
                level=LogLevel.DEBUG,
            )
        )
    )
    return await FmtResult.create(request, result)


def rules():
    return (
        *collect_rules(),
        *TaploFmtRequest.rules(),
        UnionRule(ExportableTool, Taplo),
    )
