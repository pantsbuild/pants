# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os.path
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


@rule(desc="Lint with Hadolint", level=LogLevel.DEBUG)
async def run_hadolint(request: HadolintRequest, hadolint: Hadolint) -> LintResults:
    if hadolint.skip:
        return LintResults([], linter_name="Hadolint")

    downloaded_hadolint, sources = await MultiGet(
        Get(DownloadedExternalTool, ExternalToolRequest, hadolint.get_request(Platform.current)),
        Get(
            SourceFiles,
            SourceFilesRequest(
                [field_set.sources for field_set in request.field_sets],
                for_sources_types=(DockerImageSources,),
                enable_codegen=True,
            ),
        ),
    )
    config_files = await Get(
        ConfigFiles, ConfigFilesRequest, hadolint.config_request(sources.snapshot.dirs)
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

    # As hadolint uses a single config file, we need to partition our runs per config file
    # discovered.
    files_with_config = _group_files_with_config(
        set(sources.snapshot.files),
        config_files.snapshot.files,
        not hadolint.config,
    )
    processes = [
        Process(
            argv=[downloaded_hadolint.exe, *config, *hadolint.args, *files],
            input_digest=input_digest,
            description=f"Run `hadolint` on {pluralize(len(files), 'Dockerfile')}.",
            level=LogLevel.DEBUG,
        )
        for files, config in files_with_config
    ]
    process_results = await MultiGet(Get(FallibleProcessResult, Process, p) for p in processes)
    results = [
        LintResult.from_fallible_process_result(process_result)
        for process_result in process_results
    ]
    return LintResults(results, linter_name="hadolint")


def _group_files_with_config(
    source_files: set[str], config_files: tuple[str, ...], config_files_discovered: bool
) -> list[tuple[tuple[str, ...], list[str]]]:
    """If config_files_discovered, group all source files that is in the same directory or below a
    config file, otherwise, all files will be kept in one group per config file that was provided as
    option."""
    groups = []
    consumed_files: set[str] = set()

    for config_file in config_files:
        if not config_files_discovered:
            files = source_files
        else:
            path = os.path.dirname(config_file)
            files = {source_file for source_file in source_files if source_file.startswith(path)}
        if files:
            groups.append((tuple(files), ["--config", config_file]))
            consumed_files.update(files)

    if len(consumed_files) < len(source_files):
        files = set(source_files) - consumed_files
        groups.append((tuple(files), []))

    return groups


def rules():
    return [
        *collect_rules(),
        UnionRule(LintRequest, HadolintRequest),
    ]
