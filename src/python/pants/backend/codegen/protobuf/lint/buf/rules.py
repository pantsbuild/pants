# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.codegen.protobuf.lint.buf.skip_field import SkipBufField
from pants.backend.codegen.protobuf.lint.buf.subsystem import Buf
from pants.backend.codegen.protobuf.target_types import (
    ProtobufDependenciesField,
    ProtobufSourceField,
)
from pants.core.goals.lint import LintResult, LintResults, LintTargetsRequest
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import DependenciesRequest, FieldSet, SourcesField, Target, Targets
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
    name = Buf.options_scope


@rule(desc="Lint with Buf", level=LogLevel.DEBUG)
async def run_buf(request: BufRequest, buf: Buf) -> LintResults:
    if buf.skip:
        return LintResults([], linter_name=request.name)

    all_dependencies = await MultiGet(
        Get(Targets, DependenciesRequest(field_set.dependencies))
        for field_set in request.field_sets
    )

    dependency_sources_get = Get(
        SourceFiles,
        SourceFilesRequest(
            (tgt.get(SourcesField) for dependencies in all_dependencies for tgt in dependencies),
            for_sources_types=(ProtobufSourceField,),
            enable_codegen=True,
        ),
    )

    direct_sources_get = Get(
        SourceFiles,
        SourceFilesRequest(
            (field_set.sources for field_set in request.field_sets),
            for_sources_types=(ProtobufSourceField,),
            enable_codegen=True,
        ),
    )

    download_buf_get = Get(
        DownloadedExternalTool, ExternalToolRequest, buf.get_request(Platform.current)
    )

    direct_sources, dependency_sources, downloaded_buf = await MultiGet(
        direct_sources_get, dependency_sources_get, download_buf_get
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                direct_sources.snapshot.digest,
                dependency_sources.snapshot.digest,
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
                ",".join(
                    [
                        *direct_sources.snapshot.files,
                        *dependency_sources.snapshot.files,
                    ]
                ),
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
