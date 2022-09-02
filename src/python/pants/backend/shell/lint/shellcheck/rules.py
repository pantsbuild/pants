# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.shell.lint.shellcheck.skip_field import SkipShellcheckField
from pants.backend.shell.lint.shellcheck.subsystem import Shellcheck
from pants.backend.shell.target_types import ShellDependenciesField, ShellSourceField
from pants.core.goals.lint import LintResult, LintTargetsRequest, TargetPartitions
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import DependenciesRequest, FieldSet, SourcesField, Target, Targets
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class ShellcheckFieldSet(FieldSet):
    required_fields = (ShellSourceField,)

    sources: ShellSourceField
    dependencies: ShellDependenciesField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipShellcheckField).value


class ShellcheckRequest(LintTargetsRequest):
    field_set_type = ShellcheckFieldSet
    name = Shellcheck.options_scope


@rule
async def partition_shellcheck(
    request: ShellcheckRequest.PartitionRequest[ShellcheckFieldSet], shellcheck: Shellcheck
) -> TargetPartitions[None]:
    if shellcheck.skip:
        return TargetPartitions()

    return TargetPartitions.from_field_set_partitions([request.field_sets])


@rule(desc="Lint with Shellcheck", level=LogLevel.DEBUG)
async def run_shellcheck(
    request: ShellcheckRequest.Batch[ShellcheckFieldSet, None], shellcheck: Shellcheck
) -> LintResult:
    # Shellcheck looks at direct dependencies to make sure that every symbol is defined, so we must
    # include those in the run.
    all_dependencies = await MultiGet(
        Get(Targets, DependenciesRequest(field_set.dependencies))
        for field_set in request.field_sets
    )
    direct_sources_get = Get(
        SourceFiles,
        SourceFilesRequest(
            (field_set.sources for field_set in request.field_sets),
            for_sources_types=(ShellSourceField,),
            enable_codegen=True,
        ),
    )
    dependency_sources_get = Get(
        SourceFiles,
        SourceFilesRequest(
            (tgt.get(SourcesField) for dependencies in all_dependencies for tgt in dependencies),
            for_sources_types=(ShellSourceField,),
            enable_codegen=True,
        ),
    )

    download_shellcheck_get = Get(
        DownloadedExternalTool, ExternalToolRequest, shellcheck.get_request(Platform.current)
    )

    direct_sources, dependency_sources, downloaded_shellcheck = await MultiGet(
        direct_sources_get, dependency_sources_get, download_shellcheck_get
    )

    config_files = await Get(
        ConfigFiles, ConfigFilesRequest, shellcheck.config_request(direct_sources.snapshot.dirs)
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                direct_sources.snapshot.digest,
                dependency_sources.snapshot.digest,
                downloaded_shellcheck.digest,
                config_files.snapshot.digest,
            )
        ),
    )

    process_result = await Get(
        FallibleProcessResult,
        Process(
            argv=[downloaded_shellcheck.exe, *shellcheck.args, *direct_sources.snapshot.files],
            input_digest=input_digest,
            description=f"Run Shellcheck on {pluralize(len(request.field_sets), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    result = LintResult.from_fallible_process_result(
        process_result, linter_name=Shellcheck.options_scope
    )
    return result


def rules():
    return [*collect_rules(), *ShellcheckRequest.registration_rules()]
