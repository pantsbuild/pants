# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
""""Generates trufflehog rules."""

from __future__ import annotations

from typing import Iterable

from pants.backend.tools.trufflehog.subsystem import Trufflehog
from pants.core.goals.lint import LintFilesRequest, LintResult
from pants.core.util_rules.config_files import find_config_file
from pants.core.util_rules.external_tool import download_external_tool
from pants.core.util_rules.partitions import Partitions
from pants.engine.fs import CreateDigest, FileEntry, MergeDigests, PathGlobs
from pants.engine.intrinsics import (
    create_digest_to_digest,
    digest_to_snapshot,
    directory_digest_to_digest_entries,
    merge_digests_request_to_digest,
    process_request_to_process_result,
)
from pants.engine.platform import Platform
from pants.engine.process import Process
from pants.engine.rules import Rule, collect_rules, concurrently, implicitly, rule
from pants.source.filespec import FilespecMatcher
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


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

    download_trufflehog_get = download_external_tool(trufflehog.get_request(platform))
    config_files_get = find_config_file(trufflehog.config_request())
    downloaded_trufflehog, config_digest = await concurrently(
        download_trufflehog_get, config_files_get
    )

    # The downloaded files are going to contain the `exe`, readme and license. We only want the `exe`
    entry = next(
        e
        for e in await directory_digest_to_digest_entries(downloaded_trufflehog.digest)
        if isinstance(e, FileEntry) and e.path == "trufflehog" and e.is_executable
    )

    trufflehog_digest = await create_digest_to_digest(CreateDigest([entry]))
    snapshot = await digest_to_snapshot(**implicitly(PathGlobs(request.elements)))
    input_digest = await merge_digests_request_to_digest(
        MergeDigests(
            (
                snapshot.digest,
                trufflehog_digest,
                config_digest.snapshot.digest,
            )
        )
    )

    process_result = await process_request_to_process_result(
        Process(
            argv=(
                downloaded_trufflehog.exe,
                "filesystem",
                *snapshot.files,
                "--fail",
                "--no-update",
                *(
                    ("--config", *config_digest.snapshot.files)
                    if config_digest.snapshot.files
                    else ()
                ),
                *trufflehog.args,
            ),
            input_digest=input_digest,
            description=f"Run Trufflehog on {pluralize(len(snapshot.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
        **implicitly(),
    )
    return LintResult.create(request, process_result)


def rules() -> Iterable[Rule]:
    return (
        *collect_rules(),
        *TrufflehogRequest.rules(),
    )
