# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass

from pants.backend.codegen.protobuf.lint.buf.skip_field import SkipBufFormatField
from pants.backend.codegen.protobuf.lint.buf.subsystem import BufSubsystem
from pants.backend.codegen.protobuf.target_types import (
    ProtobufDependenciesField,
    ProtobufSourceField,
)
from pants.core.goals.fmt import FmtRequest, FmtResult
from pants.core.goals.lint import LintResult, LintResults, LintTargetsRequest
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.system_binaries import (
    BinaryShims,
    BinaryShimsRequest,
    DiffBinary,
    DiffBinaryRequest,
)
from pants.engine.fs import Digest, MergeDigests
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class BufFieldSet(FieldSet):
    required_fields = (ProtobufSourceField,)

    sources: ProtobufSourceField
    dependencies: ProtobufDependenciesField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipBufFormatField).value


class BufFormatRequest(LintTargetsRequest, FmtRequest):
    field_set_type = BufFieldSet
    name = "buf-format"


@dataclass(frozen=True)
class SetupRequest:
    request: BufFormatRequest
    check_only: bool


@dataclass(frozen=True)
class Setup:
    process: Process
    original_digest: Digest


@rule(level=LogLevel.DEBUG)
async def setup_buf_format(setup_request: SetupRequest, buf: BufSubsystem) -> Setup:
    diff_binary = await Get(DiffBinary, DiffBinaryRequest())
    download_buf_get = Get(
        DownloadedExternalTool, ExternalToolRequest, buf.get_request(Platform.current)
    )
    binary_shims_get = Get(
        BinaryShims,
        BinaryShimsRequest,
        BinaryShimsRequest.for_paths(
            diff_binary,
            rationale="run `buf format`",
            output_directory=".bin",
        ),
    )
    source_files_get = Get(
        SourceFiles,
        SourceFilesRequest(field_set.sources for field_set in setup_request.request.field_sets),
    )
    downloaded_buf, binary_shims, source_files = await MultiGet(
        download_buf_get, binary_shims_get, source_files_get
    )

    source_files_snapshot = (
        source_files.snapshot
        if setup_request.request.prior_formatter_result is None
        else setup_request.request.prior_formatter_result
    )

    input_digest = await Get(
        Digest,
        MergeDigests((source_files_snapshot.digest, downloaded_buf.digest, binary_shims.digest)),
    )

    argv = [
        downloaded_buf.exe,
        "format",
        # If linting, use `-d` to error with a diff and `--exit-code` to exit with a non-zero exit code if
        # the file is not already formatted. Else, write the change with `-w`.
        *(["-d", "--exit-code"] if setup_request.check_only else ["-w"]),
        *buf.format_args,
        "--path",
        ",".join(source_files_snapshot.files),
    ]
    process = Process(
        argv=argv,
        input_digest=input_digest,
        output_files=source_files_snapshot.files,
        description=f"Run buf format on {pluralize(len(setup_request.request.field_sets), 'file')}.",
        level=LogLevel.DEBUG,
        env={"PATH": binary_shims.bin_directory},
    )
    return Setup(process, original_digest=source_files_snapshot.digest)


@rule(desc="Format with buf format", level=LogLevel.DEBUG)
async def run_buf_format(request: BufFormatRequest, buf: BufSubsystem) -> FmtResult:
    if buf.skip_format:
        return FmtResult.skip(formatter_name=request.name)
    setup = await Get(Setup, SetupRequest(request, check_only=False))
    result = await Get(ProcessResult, Process, setup.process)
    return FmtResult.from_process_result(
        result, original_digest=setup.original_digest, formatter_name=request.name
    )


@rule(desc="Lint with buf format", level=LogLevel.DEBUG)
async def run_buf_lint(request: BufFormatRequest, buf: BufSubsystem) -> LintResults:
    if buf.skip_format:
        return LintResults([], linter_name=request.name)
    setup = await Get(Setup, SetupRequest(request, check_only=True))
    result = await Get(FallibleProcessResult, Process, setup.process)
    return LintResults([LintResult.from_fallible_process_result(result)], linter_name=request.name)


def rules():
    return [
        *collect_rules(),
        UnionRule(FmtRequest, BufFormatRequest),
        UnionRule(LintTargetsRequest, BufFormatRequest),
    ]
