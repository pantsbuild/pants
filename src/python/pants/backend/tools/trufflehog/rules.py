# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
""""Generates trufflehog rules."""

from __future__ import annotations

from pants.core.goals.lint import LintFilesRequest, LintResult
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.partitions import Partitions
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestEntries,
    FileEntry,
    MergeDigests,
    PathGlobs,
    Snapshot,
)
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.source.filespec import FilespecMatcher
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

from pants.backend.tools.trufflehog.subsystem import Trufflehog


class TrufflehogRequest(LintFilesRequest):
    tool_subsystem = Trufflehog


@rule
async def partition_inputs(
    request: TrufflehogRequest.PartitionRequest, trufflehog: Trufflehog
) -> Partitions:
    """Configure the partitions scheme."""
    if trufflehog.skip or not request.files:
        return Partitions()

    matched_filepaths = FilespecMatcher(
        includes=["**"],
        excludes=trufflehog.exclude,
    ).matches(tuple(request.files))
    return Partitions.single_partition(sorted(matched_filepaths))


@rule(desc="Run Trufflehog Scan", level=LogLevel.DEBUG)
async def run_trufflehog(
    request: TrufflehogRequest.Batch,
    trufflehog: Trufflehog,
    platform: Platform,
) -> LintResult:
    """Runs the trufflehog executable against the targeted files."""

    download_trufflehog_get = Get(
        DownloadedExternalTool, ExternalToolRequest, trufflehog.get_request(platform)
    )

    config_files_get = Get(ConfigFiles, ConfigFilesRequest, trufflehog.config_request())

    downloaded_trufflehog, config_digest = await MultiGet(download_trufflehog_get, config_files_get)
    # the downloaded files are going to contain the `exe`, readme and license. We only
    # want the `exe`
    entry = next(
        e
        for e in await Get(DigestEntries, Digest, downloaded_trufflehog.digest)
        if isinstance(e, FileEntry) and e.path == "trufflehog" and e.is_executable
    )
    trufflehog_digest = await Get(Digest, CreateDigest([entry]))

    snapshot = await Get(Snapshot, PathGlobs(request.elements))

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                snapshot.digest,
                trufflehog_digest,
                config_digest.snapshot.digest,
            )
        ),
    )

    process_result = await Get(
        FallibleProcessResult,
        Process(
            argv=(
                downloaded_trufflehog.exe,
                "filesystem",
                *snapshot.files,
                "--fail",
                "-j",
                "--no-update",
                *(
                    ("--config", *config_digest.snapshot.files)
                    if config_digest.snapshot.files
                    else ()
                ),
            ),
            input_digest=input_digest,
            description=f"Run Trufflehog on {pluralize(len(snapshot.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return LintResult.create(request, process_result)


def rules() -> list:
    """Collect all the rules."""
    return [
        *collect_rules(),
        *TrufflehogRequest.rules(),
    ]
