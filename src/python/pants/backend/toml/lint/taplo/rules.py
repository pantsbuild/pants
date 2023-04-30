# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Any

from pants.backend.toml.lint.taplo.skip_field import SkipTaploField
from pants.backend.toml.lint.taplo.subsystem import Taplo
from pants.backend.toml.target_types import TomlSourceField
from pants.core.goals.fmt import FmtFilesRequest, FmtResult, FmtTargetsRequest, Partitions
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.fs import Digest, MergeDigests
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class TaploFieldSet(FieldSet):
    required_fields = (TomlSourceField,)

    sources: TomlSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipTaploField).value


class TaploFmtRequest(FmtTargetsRequest):
    field_set_type = TaploFieldSet
    tool_subsystem = Taplo
    name = Taplo.options_scope
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


@rule(desc="Format with taplo", level=LogLevel.DEBUG)
async def taplo_fmt(request: TaploFmtRequest.Batch, taplo: Taplo, platform: Platform) -> FmtResult:
    download_taplo_get = Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        taplo.get_request(platform),
    )
    config_files_get = Get(
        ConfigFiles, ConfigFilesRequest, taplo.config_request(request.snapshot.dirs)
    )
    downloaded_taplo, config_digest = await MultiGet(download_taplo_get, config_files_get)
    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                request.snapshot.digest,
                downloaded_taplo.digest,
                config_digest.snapshot.digest,
            )
        ),
    )

    argv = [
        downloaded_taplo.exe,
        "fmt",
        *taplo.args,
        *request.files,
    ]
    process = Process(
        argv=argv,
        input_digest=input_digest,
        output_files=request.files,
        description=f"Run taplo on {pluralize(len(request.files), 'file')}.",
        level=LogLevel.DEBUG,
    )

    result = await Get(ProcessResult, Process, process)
    return await FmtResult.create(request, result)


class PyprojectFmtRequest(FmtFilesRequest):
    tool_subsystem = Taplo


@rule
async def partition_pyprojects(
    request: PyprojectFmtRequest.PartitionRequest, taplo: Taplo
) -> Partitions[Any]:
    if taplo.skip:
        return Partitions()

    return Partitions.single_partition(sorted(taplo.pyproject_checker(request.files)))


@rule(desc="Format pyproject.toml files", level=LogLevel.DEBUG)
async def pyproject_toml_fmt(
    request: PyprojectFmtRequest.Batch, taplo: Taplo, platform: Platform
) -> FmtResult:
    download_taplo_get = Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        taplo.get_request(platform),
    )
    config_files_get = Get(
        ConfigFiles, ConfigFilesRequest, taplo.config_request(request.snapshot.dirs)
    )
    downloaded_taplo, config_digest = await MultiGet(download_taplo_get, config_files_get)
    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                request.snapshot.digest,
                downloaded_taplo.digest,
                config_digest.snapshot.digest,
            )
        ),
    )

    argv = [
        downloaded_taplo.exe,
        "fmt",
        *taplo.args,
        *request.files,
    ]
    process = Process(
        argv=argv,
        input_digest=input_digest,
        output_files=request.files,
        description=f"Run taplo on {pluralize(len(request.files), 'file')}.",
        level=LogLevel.DEBUG,
    )

    result = await Get(ProcessResult, Process, process)
    return await FmtResult.create(request, result)


def rules():
    return [
        *collect_rules(),
        *TaploFmtRequest.rules(),
        *PyprojectFmtRequest.rules(),
    ]
