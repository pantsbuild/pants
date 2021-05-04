# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.shell.lint.shellcheck.skip_field import SkipShellcheckField
from pants.backend.shell.lint.shellcheck.subsystem import Shellcheck
from pants.backend.shell.target_types import ShellSources
from pants.core.goals.lint import LintRequest, LintResult, LintResults
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    FieldSet,
    Sources,
    Target,
    Targets,
)
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class ShellcheckFieldSet(FieldSet):
    required_fields = (ShellSources,)

    sources: ShellSources
    dependencies: Dependencies

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipShellcheckField).value


class ShellcheckRequest(LintRequest):
    field_set_type = ShellcheckFieldSet


@rule(desc="Lint with Shellcheck", level=LogLevel.DEBUG)
async def run_shellcheck(request: ShellcheckRequest, shellcheck: Shellcheck) -> LintResults:
    if shellcheck.skip:
        return LintResults([], linter_name="Shellcheck")

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
            for_sources_types=(ShellSources,),
            enable_codegen=True,
        ),
    )
    dependency_sources_get = Get(
        SourceFiles,
        SourceFilesRequest(
            (tgt.get(Sources) for dependencies in all_dependencies for tgt in dependencies),
            for_sources_types=(ShellSources,),
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
    result = LintResult.from_fallible_process_result(process_result)
    return LintResults([result], linter_name="Shellcheck")


def rules():
    return [*collect_rules(), UnionRule(LintRequest, ShellcheckRequest)]
