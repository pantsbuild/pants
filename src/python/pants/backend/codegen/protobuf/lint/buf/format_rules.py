# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass

from pants.backend.codegen.protobuf.lint.buf.skip_field import SkipBufFormatField
from pants.backend.codegen.protobuf.lint.buf.subsystem import BufSubsystem
from pants.backend.codegen.protobuf.target_types import (
    ProtobufDependenciesField,
    ProtobufSourceField,
)
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest, Partitions
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.system_binaries import BinaryShims, BinaryShimsRequest, DiffBinary
from pants.engine.fs import Digest, MergeDigests
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.util.logging import LogLevel
from pants.util.meta import classproperty
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class BufFieldSet(FieldSet):
    required_fields = (ProtobufSourceField,)

    sources: ProtobufSourceField
    dependencies: ProtobufDependenciesField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipBufFormatField).value


class BufFormatRequest(FmtTargetsRequest):
    field_set_type = BufFieldSet
    tool_subsystem = BufSubsystem  # type: ignore[assignment]

    @classproperty
    def tool_name(cls) -> str:
        return "buf format"

    @classproperty
    def tool_id(cls) -> str:
        return "buf-format"


@rule
async def partition_buf(
    request: BufFormatRequest.PartitionRequest, buf: BufSubsystem
) -> Partitions:
    return (
        Partitions()
        if buf.format_skip
        else Partitions.single_partition(
            field_set.sources.file_path for field_set in request.field_sets
        )
    )


@rule(desc="Format with buf format", level=LogLevel.DEBUG)
async def run_buf_format(
    request: BufFormatRequest.Batch, buf: BufSubsystem, diff_binary: DiffBinary, platform: Platform
) -> FmtResult:
    download_buf_get = Get(DownloadedExternalTool, ExternalToolRequest, buf.get_request(platform))
    binary_shims_get = Get(
        BinaryShims,
        BinaryShimsRequest,
        BinaryShimsRequest.for_paths(
            diff_binary,
            rationale="run `buf format`",
        ),
    )
    downloaded_buf, binary_shims = await MultiGet(download_buf_get, binary_shims_get)

    input_digest = await Get(
        Digest,
        MergeDigests((request.snapshot.digest, downloaded_buf.digest)),
    )

    argv = [
        downloaded_buf.exe,
        "format",
        "-w",
        *buf.format_args,
        "--path",
        ",".join(request.files),
    ]
    result = await Get(
        ProcessResult,
        Process(
            argv=argv,
            input_digest=input_digest,
            output_files=request.files,
            description=f"Run buf format on {pluralize(len(request.files), 'file')}.",
            level=LogLevel.DEBUG,
            env={"PATH": binary_shims.path_component},
            immutable_input_digests=binary_shims.immutable_input_digests,
        ),
    )
    return await FmtResult.create(request, result)


def rules():
    return [
        *collect_rules(),
        *BufFormatRequest.rules(),
    ]
