# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from pants.backend.python.util_rules.pex import Pex, PexProcess, PexRequest
from pants.backend.tools.yamllint.subsystem import Yamllint
from pants.core.goals.lint import LintFilesRequest, LintResult
from pants.core.util_rules.partitions import Partition, Partitions
from pants.engine.fs import Digest, DigestSubset, MergeDigests, PathGlobs
from pants.engine.internals.native_engine import FilespecMatcher, Snapshot
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.dirutil import find_nearest_ancestor_file, group_by_dir
from pants.util.frozendict import FrozenDict
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


@dataclass(frozen=True)
class YamllintConfigFilesRequest:
    filepaths: tuple[str, ...]


@dataclass(frozen=True)
class YamllintConfigFiles:
    snapshot: Snapshot
    source_dir_to_config_files: FrozenDict[str, str]


# @TODO: This logic is very similar, but not identical to the one for scalafmt. It should be generalized and shared.
@rule
async def gather_config_files(
    request: YamllintConfigFilesRequest, yamllint: Yamllint
) -> YamllintConfigFiles:
    """Gather yamllint configuration files."""
    source_dirs = frozenset(os.path.dirname(path) for path in request.filepaths)
    source_dirs_with_ancestors = {"", *source_dirs}
    for source_dir in source_dirs:
        source_dir_parts = source_dir.split(os.path.sep)
        source_dir_parts.pop()
        while source_dir_parts:
            source_dirs_with_ancestors.add(os.path.sep.join(source_dir_parts))
            source_dir_parts.pop()

    config_file_globs = [
        os.path.join(dir, yamllint.config_file_name) for dir in source_dirs_with_ancestors
    ]
    config_files_snapshot = await Get(Snapshot, PathGlobs(config_file_globs))
    config_files_set = set(config_files_snapshot.files)

    source_dir_to_config_file: dict[str, str] = {}
    for source_dir in source_dirs:
        config_file = find_nearest_ancestor_file(
            config_files_set, source_dir, yamllint.config_file_name
        )
        if config_file:
            source_dir_to_config_file[source_dir] = config_file

    return YamllintConfigFiles(config_files_snapshot, FrozenDict(source_dir_to_config_file))


@rule
async def partition_inputs(
    request: YamllintRequest.PartitionRequest, yamllint: Yamllint
) -> Partitions[Any, PartitionInfo]:
    import pantsdebug; pantsdebug.settrace_5678(True)
    if yamllint.skip:
        return Partitions()

    matching_filepaths = FilespecMatcher(
        includes=yamllint.file_glob_include, excludes=yamllint.file_glob_exclude
    ).matches(request.files)

    config_files = await Get(
        YamllintConfigFiles, YamllintConfigFilesRequest(filepaths=tuple(sorted(matching_filepaths)))
    )
    import pantsdebug; pantsdebug.settrace_5678(True)

    default_source_files: set[str] = set()
    source_files_by_config_file: dict[str, set[str]] = defaultdict(set)
    for source_dir, files_in_source_dir in group_by_dir(matching_filepaths).items():
        files = (os.path.join(source_dir, name) for name in files_in_source_dir)
        if source_dir in config_files.source_dir_to_config_files:
            config_file = config_files.source_dir_to_config_files[source_dir]
            source_files_by_config_file[config_file].update(files)
        else:
            default_source_files.update(files)

    config_file_snapshots = await MultiGet(
        Get(Snapshot, DigestSubset(config_files.snapshot.digest, PathGlobs([config_file])))
        for config_file in source_files_by_config_file
    )
    import pantsdebug; pantsdebug.settrace_5678()

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
    yamllint_bin = await Get(Pex, PexRequest, yamllint.to_pex_request())

    partition_info = request.partition_metadata

    snapshot = await Get(Snapshot, PathGlobs(request.elements))

    input_digest = await Get(
        Digest,
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
        ),
    )

    process_result = await Get(
        FallibleProcessResult,
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
        ),
    )
    return LintResult.create(request, process_result)


def rules():
    return [*collect_rules(), *YamllintRequest.rules()]
