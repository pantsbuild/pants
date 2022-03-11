# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass

from pants.backend.codegen.protobuf.lint.buf.skip_field import SkipBufField
from pants.backend.codegen.protobuf.lint.buf.subsystem import BufSubsystem
from pants.backend.codegen.protobuf.target_types import (
    ProtobufDependenciesField,
    ProtobufSourceField,
)
from pants.core.goals.lint import LintResult, LintResults, LintTargetsRequest
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.fs import Digest, MergeDigests
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet, Target, TransitiveTargets, TransitiveTargetsRequest
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
        return tgt.get(SkipBufField).value


class BufRequest(LintTargetsRequest):
    field_set_type = BufFieldSet
    name = BufSubsystem.options_scope


@rule(desc="Lint with Buf", level=LogLevel.DEBUG)
async def run_buf(request: BufRequest, buf: BufSubsystem) -> LintResults:
    if buf.skip:
        return LintResults([], linter_name=request.name)

    transitive_targets = await Get(
        TransitiveTargets,
        TransitiveTargetsRequest((field_set.address for field_set in request.field_sets)),
    )

    all_stripped_sources_request = Get(
        StrippedSourceFiles,
        SourceFilesRequest(
            tgt[ProtobufSourceField]
            for tgt in transitive_targets.closure
            if tgt.has_field(ProtobufSourceField)
        ),
    )
    target_stripped_sources_request = Get(
        StrippedSourceFiles,
        SourceFilesRequest(
            (field_set.sources for field_set in request.field_sets),
            for_sources_types=(ProtobufSourceField,),
            enable_codegen=True,
        ),
    )

    download_buf_get = Get(
        DownloadedExternalTool, ExternalToolRequest, buf.get_request(Platform.current)
    )

    target_sources_stripped, all_sources_stripped, downloaded_buf = await MultiGet(
        target_stripped_sources_request, all_stripped_sources_request, download_buf_get
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                target_sources_stripped.snapshot.digest,
                all_sources_stripped.snapshot.digest,
                downloaded_buf.digest,
            )
        ),
    )

    process_result = await Get(
        FallibleProcessResult,
        Process(
            argv=[
                downloaded_buf.exe,
                "lint",
                *buf.args,
                "--path",
                ",".join(target_sources_stripped.snapshot.files),
            ],
            input_digest=input_digest,
            description=f"Run Buf on {pluralize(len(request.field_sets), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    result = LintResult.from_fallible_process_result(process_result)

    return LintResults([result], linter_name=request.name)


def rules():
    return [*collect_rules(), UnionRule(LintTargetsRequest, BufRequest)]
