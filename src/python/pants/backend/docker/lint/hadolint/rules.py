# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.docker.lint.hadolint.skip_field import SkipHadolintField
from pants.backend.docker.lint.hadolint.subsystem import Hadolint
from pants.backend.docker.target_types import DockerImageSources
from pants.core.goals.lint import LintRequest, LintResult, LintResults
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class HadolintFieldSet(FieldSet):
    required_fields = (DockerImageSources,)

    sources: DockerImageSources

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipHadolintField).value


class HadolintRequest(LintRequest):
    field_set_type = HadolintFieldSet


def generate_argv(source_files: SourceFiles, hadolint: Hadolint) -> tuple[str, ...]:
    args = []
    if hadolint.config:
        args.append(f"--config={hadolint.config}")
    args.extend(hadolint.args)
    args.extend(source_files.files)
    return tuple(args)


@rule(desc="Lint with Hadolint", level=LogLevel.DEBUG)
async def run_hadolint(request: HadolintRequest, hadolint: Hadolint) -> LintResults:
    if hadolint.skip:
        return LintResults([], linter_name="Hadolint")

    downloaded_hadolint, sources, config_files = await MultiGet(
        Get(DownloadedExternalTool, ExternalToolRequest, hadolint.get_request(Platform.current)),
        Get(
            SourceFiles,
            SourceFilesRequest(
                [field_set.sources for field_set in request.field_sets],
                for_sources_types=(DockerImageSources,),
                enable_codegen=True,
            ),
        ),
        Get(ConfigFiles, ConfigFilesRequest, hadolint.config_request()),
    )
    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                sources.snapshot.digest,
                downloaded_hadolint.digest,
                config_files.snapshot.digest,
            )
        ),
    )
    process_result = await Get(
        FallibleProcessResult,
        Process(
            argv=[downloaded_hadolint.exe, *generate_argv(sources, hadolint)],
            input_digest=input_digest,
            description=f"Run `hadolint` on {pluralize(len(sources.files), 'Dockerfile')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return LintResults(
        [LintResult.from_fallible_process_result(process_result)], linter_name="hadolint"
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(LintRequest, HadolintRequest),
    ]
