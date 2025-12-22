# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.terraform.lint.tfsec.tfsec import SkipTfSecField, TFSec, TfSecRequest
from pants.backend.terraform.target_types import TerraformModuleTarget
from pants.core.goals.lint import REPORT_DIR, LintResult
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules import config_files
from pants.core.util_rules.config_files import find_config_file
from pants.core.util_rules.external_tool import download_external_tool
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.engine.fs import CreateDigest, Directory, MergeDigests, RemovePrefix
from pants.engine.intrinsics import create_digest, execute_process, merge_digests, remove_prefix
from pants.engine.platform import Platform
from pants.engine.process import Process
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@rule
async def run_tfsec(request: TfSecRequest.Batch, tfsec: TFSec, platform: Platform) -> LintResult:
    (
        downloaded_tfsec,
        sources,
        config_file,
        custom_checks,
        report_directory,
    ) = await concurrently(
        download_external_tool(tfsec.get_request(platform)),
        determine_source_files(SourceFilesRequest(fs.sources for fs in request.elements)),
        find_config_file(tfsec.config_request()),
        find_config_file(tfsec.custom_checks_request()),
        # Ensure that the empty report dir exists.
        create_digest(CreateDigest([Directory(REPORT_DIR)])),
    )

    input_digest = await merge_digests(
        MergeDigests(
            (
                downloaded_tfsec.digest,
                sources.snapshot.digest,
                config_file.snapshot.digest,
                custom_checks.snapshot.digest,
                report_directory,
            )
        )
    )

    computed_args = []
    if tfsec.config:
        computed_args.append(f"--config-file={tfsec.config}")
    if tfsec.custom_check_dir:
        computed_args.append(f"--custom-check-dir={tfsec.custom_check_dir}")

    if tfsec.report_name:
        computed_args.append(f"--out={REPORT_DIR}/{tfsec.report_name}")

    argv = [
        downloaded_tfsec.exe,
        *computed_args,
        *tfsec.args,
    ]
    result = await execute_process(
        Process(
            argv=argv,
            input_digest=input_digest,
            output_directories=(REPORT_DIR,),
            description=f"Run tfsec on {pluralize(len(sources.files), 'file')}",
            level=LogLevel.DEBUG,
        ),
        **implicitly(),
    )

    report = await remove_prefix(RemovePrefix(result.output_digest, REPORT_DIR))
    return LintResult.create(request, result, report=report)


def rules():
    return [
        *collect_rules(),
        *TfSecRequest.rules(),
        *config_files.rules(),
        TerraformModuleTarget.register_plugin_field(SkipTfSecField),
        UnionRule(ExportableTool, TFSec),
    ]
