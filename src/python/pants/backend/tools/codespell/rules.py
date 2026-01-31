# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from pants.backend.python.util_rules.pex import PexProcess, create_pex
from pants.backend.tools.codespell.subsystem import Codespell
from pants.core.goals.lint import LintFilesRequest, LintResult
from pants.core.util_rules.config_files import (
    ConfigFiles,
    ConfigFilesRequest,
    GatherConfigFilesByDirectoriesRequest,
    find_config_file,
    gather_config_files_by_workspace_dir,
)
from pants.core.util_rules.partitions import Partition, Partitions
from pants.engine.fs import DigestSubset, MergeDigests, PathGlobs
from pants.engine.internals.native_engine import FilespecMatcher, Snapshot
from pants.engine.intrinsics import digest_to_snapshot, execute_process, merge_digests
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.util.dirutil import group_by_dir
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


class CodespellRequest(LintFilesRequest):
    tool_subsystem = Codespell  # type: ignore[assignment]


@dataclass(frozen=True)
class PartitionInfo:
    config_snapshot: Snapshot | None
    # If True, this partition has no .codespellrc ancestor and should try
    # to discover setup.cfg/pyproject.toml at runtime
    discover_root_config: bool = False

    @property
    def description(self) -> str:
        if self.config_snapshot:
            return self.config_snapshot.files[0]
        elif self.discover_root_config:
            return "<root config discovery>"
        else:
            return "<default>"


@rule
async def partition_inputs(
    request: CodespellRequest.PartitionRequest, codespell: Codespell
) -> Partitions[Any, PartitionInfo]:
    if codespell.skip:
        return Partitions()

    matching_filepaths = FilespecMatcher(
        includes=codespell.file_glob_include, excludes=codespell.file_glob_exclude
    ).matches(request.files)

    # First, find .codespellrc files for partitioning
    config_files = await gather_config_files_by_workspace_dir(
        GatherConfigFilesByDirectoriesRequest(
            tool_name=codespell.name,
            config_filename=codespell.config_file_name,
            filepaths=tuple(sorted(matching_filepaths)),
            orphan_filepath_behavior=codespell.orphan_files_behavior,
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
                        tuple(sorted(default_source_files)),
                        PartitionInfo(config_snapshot=None, discover_root_config=True),
                    ),
                )
                if default_source_files
                else ()
            ),
        )
    )


@rule(desc="Lint with codespell", level=LogLevel.DEBUG)
async def run_codespell(
    request: CodespellRequest.Batch[str, PartitionInfo],
    codespell: Codespell,
) -> LintResult:
    partition_info = request.partition_metadata

    codespell_pex_get = create_pex(codespell.to_pex_request())

    # If this partition has no .codespellrc, try to discover setup.cfg/pyproject.toml at root
    root_config: ConfigFiles | None = None
    if partition_info.discover_root_config:
        codespell_pex, root_config = await concurrently(
            codespell_pex_get,
            find_config_file(
                ConfigFilesRequest(
                    discovery=True,
                    check_existence=[".codespellrc"],
                    check_content={
                        "setup.cfg": b"[codespell]",
                        "pyproject.toml": b"[tool.codespell]",
                    },
                )
            ),
        )
    else:
        codespell_pex = await codespell_pex_get

    snapshot = await digest_to_snapshot(**implicitly(PathGlobs(request.elements)))

    # Determine which config to use and which flag to pass
    # - .codespellrc and setup.cfg use --config (INI format)
    # - pyproject.toml uses --toml (TOML format)
    config_snapshot = partition_info.config_snapshot
    config_args: tuple[str, ...] = ()

    if config_snapshot is not None:
        # We have a .codespellrc from directory-based discovery
        config_args = ("--config", config_snapshot.files[0])
    elif root_config is not None and root_config.snapshot.files:
        # We found a config at root
        config_file = root_config.snapshot.files[0]
        config_snapshot = root_config.snapshot
        if config_file.endswith("pyproject.toml"):
            config_args = ("--toml", config_file)
        else:
            # .codespellrc or setup.cfg use --config
            config_args = ("--config", config_file)

    input_digest = await merge_digests(
        MergeDigests(
            (
                snapshot.digest,
                codespell_pex.digest,
                *((config_snapshot.digest,) if config_snapshot else ()),
            )
        )
    )

    process_result = await execute_process(
        **implicitly(
            PexProcess(
                codespell_pex,
                argv=(
                    *config_args,
                    *codespell.args,
                    *snapshot.files,
                ),
                input_digest=input_digest,
                description=f"Run codespell on {pluralize(len(snapshot.files), 'file')}.",
                level=LogLevel.DEBUG,
            )
        )
    )
    return LintResult.create(request, process_result)


def rules():
    return [*collect_rules(), *CodespellRequest.rules()]
