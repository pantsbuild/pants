# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.terraform.lint.tfsec.tfsec import TFSec, TfSecRequest
from pants.core.goals.lint import LintResult
from pants.core.util_rules import config_files
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.logging import LogLevel


@rule
async def run_tfsec(request: TfSecRequest.Batch, tfsec: TFSec, platform: Platform) -> LintResult:
    downloaded_tfsec, sources, config_file = await MultiGet(
        Get(DownloadedExternalTool, ExternalToolRequest, tfsec.get_request(platform)),
        Get(SourceFiles, SourceFilesRequest(fs.sources for fs in request.elements)),
        Get(ConfigFiles, ConfigFilesRequest, tfsec.config_request()),
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                downloaded_tfsec.digest,
                sources.snapshot.digest,
                config_file.snapshot.digest,
            )
        ),
    )

    computed_args = []
    if tfsec.config:
        computed_args = [f"--config-file={tfsec.config}"]

    argv = [
        downloaded_tfsec.exe,
        *computed_args,
        *tfsec.args,
    ]
    # raise ValueError(argv)
    process_result = await Get(
        FallibleProcessResult,
        Process(
            argv=argv,
            input_digest=input_digest,
            description="Run tfsec",
            level=LogLevel.DEBUG,
        ),
    )

    return LintResult.create(request, process_result)


def rules():
    return [
        *collect_rules(),
        *TfSecRequest.rules(),
        *config_files.rules(),
    ]
