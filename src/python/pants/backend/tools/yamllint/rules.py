# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from pants.backend.python.util_rules.pex import PexProcess, create_pex
from pants.backend.tools.yamllint.subsystem import Yamllint
from pants.core.goals.lint import LintFilesRequest, LintResult
from pants.core.util_rules.config_files import (
    GatherConfigFilesByDirectoriesRequest,
    gather_config_files_by_workspace_dir,
)
from pants.core.util_rules.partitions import Partition, Partitions
from pants.engine.fs import DigestSubset, MergeDigests, PathGlobs
from pants.engine.internals.native_engine import FilespecMatcher, Snapshot
from pants.engine.intrinsics import (
    digest_to_snapshot,
    merge_digests_request_to_digest,
    process_request_to_process_result,
)
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.util.dirutil import group_by_dir
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


class YamllintRequest(LintFilesRequest):
    tool_subsystem = Yamllint


@dataclass(frozen=True)
class PartitionInfo:
    config_snapshot: Snapshot | None

    @property
    def description(self) -> str:
        if self.config_snapshot:
            return self.config_snapshot.files[0]
        else:
            return "<default>"


@rule
async def partition_inputs(
    request: YamllintRequest.PartitionRequest, yamllint: Yamllint
) -> Partitions[Any, PartitionInfo]:
    if yamllint.skip:
        return Partitions()

    matching_filepaths = FilespecMatcher(
        includes=yamllint.file_glob_include, excludes=yamllint.file_glob_exclude
    ).matches(request.files)

    config_files = await gather_config_files_by_workspace_dir(
        GatherConfigFilesByDirectoriesRequest(
            tool_name=yamllint.name,
            config_filename=yamllint.config_file_name,
            filepaths=tuple(sorted(matching_filepaths)),
            orphan_filepath_behavior=yamllint.orphan_files_behavior,
        )
    )

    default_source_files: set[str] = set()
    source_files_by_config_file: dict[str, set[str]] = defaultdict(set)
    for source_dir, files_in_source_dir in group_by_dir(matching_filepaths).items():
        files = (os.path.join(source_dir, name) for name in files_in_source_dir)
        if source_dir in config_files.source_dir_to_config_file:
            config_file = config_files.source_dir_to_config_file[source_dir]
            source_files_by_config_file[config_file].update(files)
        else:
            default_source_files.update(files)

    config_file_snapshots = await concurrently(
        digest_to_snapshot(
            **implicitly(DigestSubset(config_files.snapshot.digest, PathGlobs([config_file])))
        )
        for config_file in source_files_by_config_file
    )

    return Partitions(
        (
            *(
                Partition(tuple(sorted(files)), PartitionInfo(config_snapshot=config_snapshot))
                for files, config_snapshot in zip(
                    source_files_by_config_file.values(), config_file_snapshots
                )
            ),
            *(
                (
                    Partition(
                        tuple(sorted(default_source_files)), PartitionInfo(config_snapshot=None)
                    ),
                )
                if default_source_files
                else ()
            ),
        )
    )


@rule(desc="Lint using yamllint", level=LogLevel.DEBUG)
async def run_yamllint(
    request: YamllintRequest.Batch[str, PartitionInfo], yamllint: Yamllint
) -> LintResult:
    partition_info = request.partition_metadata

    yamllint_bin = await create_pex(yamllint.to_pex_request())
    snapshot = await digest_to_snapshot(**implicitly(PathGlobs(request.elements)))
    input_digest = await merge_digests_request_to_digest(
        MergeDigests(
            (
                snapshot.digest,
                yamllint_bin.digest,
                *(
                    (partition_info.config_snapshot.digest,)
                    if partition_info.config_snapshot
                    else ()
                ),
            )
        )
    )

    process_result = await process_request_to_process_result(
        **implicitly(
            PexProcess(
                yamllint_bin,
                argv=(
                    *(
                        ("-c", partition_info.config_snapshot.files[0])
                        if partition_info.config_snapshot
                        else ()
                    ),
                    *yamllint.args,
                    *snapshot.files,
                ),
                input_digest=input_digest,
                description=f"Run yamllint on {pluralize(len(request.elements), 'file')}.",
                level=LogLevel.DEBUG,
            )
        )
    )
    return LintResult.create(request, process_result)


def rules():
    return [*collect_rules(), *YamllintRequest.rules()]
