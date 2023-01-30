# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os.path
from collections import defaultdict
from dataclasses import dataclass
from typing import cast

from pants.backend.scala.lint.scalafmt.skip_field import SkipScalafmtField
from pants.backend.scala.lint.scalafmt.subsystem import ScalafmtSubsystem
from pants.backend.scala.target_types import ScalaSourceField
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest, Partitions
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.util_rules.partitions import Partition
from pants.engine.fs import Digest, DigestSubset, MergeDigests, PathGlobs, Snapshot
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.jvm.goals import lockfile
from pants.jvm.jdk_rules import InternalJdk, JvmProcess
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool, GenerateJvmToolLockfileSentinel
from pants.util.dirutil import find_nearest_ancestor_file, group_by_dir
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

_SCALAFMT_CONF_FILENAME = ".scalafmt.conf"


@dataclass(frozen=True)
class ScalafmtFieldSet(FieldSet):
    required_fields = (ScalaSourceField,)

    source: ScalaSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipScalafmtField).value


class ScalafmtRequest(FmtTargetsRequest):
    field_set_type = ScalafmtFieldSet
    tool_subsystem = ScalafmtSubsystem


class ScalafmtToolLockfileSentinel(GenerateJvmToolLockfileSentinel):
    resolve_name = ScalafmtSubsystem.options_scope


@dataclass(frozen=True)
class GatherScalafmtConfigFilesRequest:
    filepaths: tuple[str, ...]


@dataclass(frozen=True)
class ScalafmtConfigFiles:
    snapshot: Snapshot
    source_dir_to_config_file: FrozenDict[str, str]


@dataclass(frozen=True)
class PartitionInfo:
    classpath_entries: tuple[str, ...]
    config_snapshot: Snapshot
    extra_immutable_input_digests: FrozenDict[str, Digest]

    @property
    def description(self) -> str:
        return self.config_snapshot.files[0]


# @TODO: This logic is very similar, but not identical to the one for yamllint. It should be generalized and shared.
@rule
async def gather_scalafmt_config_files(
    request: GatherScalafmtConfigFilesRequest,
) -> ScalafmtConfigFiles:
    """Gather scalafmt config files and identify which config files to use for each source
    directory."""
    source_dirs = frozenset(os.path.dirname(path) for path in request.filepaths)

    source_dirs_with_ancestors = {"", *source_dirs}
    for source_dir in source_dirs:
        source_dir_parts = source_dir.split(os.path.sep)
        source_dir_parts.pop()
        while source_dir_parts:
            source_dirs_with_ancestors.add(os.path.sep.join(source_dir_parts))
            source_dir_parts.pop()

    config_file_globs = [
        os.path.join(dir, _SCALAFMT_CONF_FILENAME) for dir in source_dirs_with_ancestors
    ]
    config_files_snapshot = await Get(Snapshot, PathGlobs(config_file_globs))
    config_files_set = set(config_files_snapshot.files)

    source_dir_to_config_file: dict[str, str] = {}
    for source_dir in source_dirs:
        config_file = find_nearest_ancestor_file(
            config_files_set, source_dir, _SCALAFMT_CONF_FILENAME
        )
        if not config_file:
            raise ValueError(
                f"No scalafmt config file (`{_SCALAFMT_CONF_FILENAME}`) found for "
                f"source directory '{source_dir}'"
            )
        source_dir_to_config_file[source_dir] = config_file

    return ScalafmtConfigFiles(config_files_snapshot, FrozenDict(source_dir_to_config_file))


@rule
async def partition_scalafmt(
    request: ScalafmtRequest.PartitionRequest, tool: ScalafmtSubsystem
) -> Partitions[PartitionInfo]:
    if tool.skip:
        return Partitions()

    toolcp_relpath = "__toolcp"

    filepaths = tuple(field_set.source.file_path for field_set in request.field_sets)
    lockfile_request = await Get(GenerateJvmLockfileFromTool, ScalafmtToolLockfileSentinel())
    tool_classpath, config_files = await MultiGet(
        Get(ToolClasspath, ToolClasspathRequest(lockfile=lockfile_request)),
        Get(
            ScalafmtConfigFiles,
            GatherScalafmtConfigFilesRequest(filepaths),
        ),
    )

    extra_immutable_input_digests = {
        toolcp_relpath: tool_classpath.digest,
    }

    # Partition the work by which source files share the same config file (regardless of directory).
    source_files_by_config_file: dict[str, set[str]] = defaultdict(set)
    for source_dir, files_in_source_dir in group_by_dir(filepaths).items():
        config_file = config_files.source_dir_to_config_file[source_dir]
        source_files_by_config_file[config_file].update(
            os.path.join(source_dir, name) for name in files_in_source_dir
        )

    config_file_snapshots = await MultiGet(
        Get(Snapshot, DigestSubset(config_files.snapshot.digest, PathGlobs([config_file])))
        for config_file in source_files_by_config_file
    )

    return Partitions(
        Partition(
            tuple(files),
            PartitionInfo(
                classpath_entries=tuple(tool_classpath.classpath_entries(toolcp_relpath)),
                config_snapshot=config_snapshot,
                extra_immutable_input_digests=FrozenDict(extra_immutable_input_digests),
            ),
        )
        for files, config_snapshot in zip(
            source_files_by_config_file.values(), config_file_snapshots
        )
    )


@rule(desc="Format with scalafmt", level=LogLevel.DEBUG)
async def scalafmt_fmt(
    request: ScalafmtRequest.Batch, jdk: InternalJdk, tool: ScalafmtSubsystem
) -> FmtResult:
    partition_info = cast(PartitionInfo, request.partition_metadata)
    merged_digest = await Get(
        Digest,
        MergeDigests([partition_info.config_snapshot.digest, request.snapshot.digest]),
    )

    result = await Get(
        ProcessResult,
        JvmProcess(
            jdk=jdk,
            argv=[
                "org.scalafmt.cli.Cli",
                f"--config={partition_info.config_snapshot.files[0]}",
                "--non-interactive",
                *request.files,
            ],
            classpath_entries=partition_info.classpath_entries,
            input_digest=merged_digest,
            output_files=request.files,
            extra_jvm_options=tool.jvm_options,
            extra_immutable_input_digests=partition_info.extra_immutable_input_digests,
            # extra_nailgun_keys=request.extra_immutable_input_digests,
            use_nailgun=False,
            description=f"Run `scalafmt` on {pluralize(len(request.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )

    return await FmtResult.create(request, result)


@rule
def generate_scalafmt_lockfile_request(
    _: ScalafmtToolLockfileSentinel, tool: ScalafmtSubsystem
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool.create(tool)


def rules():
    return [
        *collect_rules(),
        *lockfile.rules(),
        *ScalafmtRequest.rules(),
        UnionRule(GenerateToolLockfileSentinel, ScalafmtToolLockfileSentinel),
    ]
