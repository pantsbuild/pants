# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.terraform.lint.tfsec.tfsec import TfSec, TfSecRequest
from pants.core.goals.lint import LintResult
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.logging import LogLevel


@rule
async def run_tfsec(request: TfSecRequest.Batch, tfsec: TfSec, platform: Platform) -> LintResult:
    get_tfsec = Get(DownloadedExternalTool, ExternalToolRequest, tfsec.get_request(platform))
    sources_request = Get(SourceFiles, SourceFilesRequest(fs.sources for fs in request.elements))

    downloaded_tfsec, sources = await MultiGet(get_tfsec, sources_request)

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                downloaded_tfsec.digest,
                sources.snapshot.digest,
            )
        ),
    )

    process_result = await Get(
        FallibleProcessResult,
        Process(
            argv=[
                downloaded_tfsec.exe,
                *tfsec.args,
            ],
            input_digest=input_digest,
            description="Run tfsec",
            level=LogLevel.DEBUG,
        ),
    )

    return LintResult.create(request, process_result)


def rules():
    return [*collect_rules(), *TfSecRequest.rules()]
