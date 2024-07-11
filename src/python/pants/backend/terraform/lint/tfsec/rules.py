# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.terraform.lint.tfsec.tfsec import SkipTfSecField, TFSec, TfSecRequest
from pants.backend.terraform.target_types import TerraformModuleTarget
from pants.core.goals.lint import REPORT_DIR, LintResult
from pants.core.util_rules import config_files
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import CreateDigest, Digest, Directory, MergeDigests, RemovePrefix
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@rule
async def run_tfsec(request: TfSecRequest.Batch, tfsec: TFSec, platform: Platform) -> LintResult:
    (
        downloaded_tfsec,
        sources,
        config_file,
        report_directory,
    ) = await MultiGet(
        Get(DownloadedExternalTool, ExternalToolRequest, tfsec.get_request(platform)),
        Get(SourceFiles, SourceFilesRequest(fs.sources for fs in request.elements)),
        Get(ConfigFiles, ConfigFilesRequest, tfsec.config_request()),
        # Ensure that the empty report dir exists.
        Get(Digest, CreateDigest([Directory(REPORT_DIR)])),
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                downloaded_tfsec.digest,
                sources.snapshot.digest,
                config_file.snapshot.digest,
                report_directory,
            )
        ),
    )

    computed_args = []
    if tfsec.config:
        computed_args.append(f"--config-file={tfsec.config}")

    if tfsec.report_name:
        computed_args.append(f"--out={REPORT_DIR}/{tfsec.report_name}")

    argv = [
        downloaded_tfsec.exe,
        *computed_args,
        *tfsec.args,
    ]
    result = await Get(
        FallibleProcessResult,
        Process(
            argv=argv,
            input_digest=input_digest,
            output_directories=(REPORT_DIR,),
            description=f"Run tfsec on {pluralize(len(sources.files), 'file')}",
            level=LogLevel.DEBUG,
        ),
    )

    report = await Get(Digest, RemovePrefix(result.output_digest, REPORT_DIR))
    return LintResult.create(request, result, report=report)


def rules():
    return [
        *collect_rules(),
        *TfSecRequest.rules(),
        *config_files.rules(),
        TerraformModuleTarget.register_plugin_field(SkipTfSecField),
    ]
