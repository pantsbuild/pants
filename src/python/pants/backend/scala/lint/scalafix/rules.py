# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os.path
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable, Optional, cast

from pants.backend.scala.lint.scalafix.skip_field import SkipScalafixField
from pants.backend.scala.lint.scalafix.subsystem import ScalafixSubsystem
from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.backend.scala.subsystems.scalac import Scalac
from pants.backend.scala.target_types import ScalaDependenciesField, ScalaSourceField
from pants.core.goals.fix import FixResult, FixTargetsRequest
from pants.core.goals.fmt import Partitions
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.util_rules.partitions import Partition
from pants.engine.fs import Digest, DigestSubset, MergeDigests, PathGlobs, Snapshot
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import DependenciesRequest, FieldSet, Target
from pants.engine.unions import UnionRule
from pants.jvm.classpath import Classpath
from pants.jvm.compile import ClasspathEntry
from pants.jvm.goals import lockfile
from pants.jvm.jdk_rules import InternalJdk, JvmProcess
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool, GenerateJvmToolLockfileSentinel
from pants.jvm.resolve.key import CoursierResolveKey
from pants.util.dirutil import find_nearest_ancestor_file, group_by_dir
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize, softwrap


@dataclass(frozen=True)
class ScalafixFieldSet(FieldSet):
    required_fields = (ScalaSourceField,)

    source: ScalaSourceField
    dependencies: ScalaDependenciesField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipScalafixField).value


class ScalafixRequest(FixTargetsRequest):
    field_set_type = ScalafixFieldSet
    tool_subsystem = ScalafixSubsystem


@dataclass(frozen=True)
class GatherScalafixConfigFilesRequest:
    filepaths: tuple[str, ...]


@dataclass(frozen=True)
class ScalafixConfigFiles:
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


class ScalafixToolLockfileSentinel(GenerateJvmToolLockfileSentinel):
    resolve_name = ScalafixSubsystem.options_scope


@rule
async def gather_scalafix_config_files(
    request: GatherScalafixConfigFilesRequest, scalafix: ScalafixSubsystem
) -> ScalafixConfigFiles:
    source_dirs = frozenset(os.path.dirname(path) for path in request.filepaths)

    source_dirs_with_ancestors = {"", *source_dirs}
    for source_dir in source_dirs:
        source_dir_parts = source_dir.split(os.path.sep)
        source_dir_parts.pop()
        while source_dir_parts:
            source_dirs_with_ancestors.add(os.path.sep.join(source_dir_parts))
            source_dir_parts.pop()

    config_file_globs = [
        os.path.join(dir, scalafix.config_file_name) for dir in source_dirs_with_ancestors
    ]
    config_files_snapshot = await Get(Snapshot, PathGlobs(config_file_globs))
    config_files_set = set(config_files_snapshot.files)

    source_dir_to_config_file: dict[str, str] = {}
    for source_dir in source_dirs:
        config_file = find_nearest_ancestor_file(
            config_files_set, source_dir, scalafix.config_file_name
        )
        if not config_file:
            raise ValueError(
                softwrap(
                    f"""
                    No scalafix config file (`{scalafix.config_file_name}`) found for
                    source directory '{source_dir}'.
                    """
                )
            )
        source_dir_to_config_file[source_dir] = config_file

    return ScalafixConfigFiles(config_files_snapshot, FrozenDict(source_dir_to_config_file))


@rule
async def partition_scalafix(
    request: ScalafixRequest.PartitionRequest, tool: ScalafixSubsystem
) -> Partitions[PartitionInfo]:
    if tool.skip:
        return Partitions()

    toolcp_relpath = "__toolcp"

    filepaths = tuple(field_set.source.file_path for field_set in request.field_sets)
    classpaths = await MultiGet(
        Get(Classpath, DependenciesRequest(field_set.dependencies))
        for field_set in request.field_sets
    )
    classpath_by_filepath = dict(zip(filepaths, classpaths))

    lockfile_request = await Get(GenerateJvmLockfileFromTool, ScalafixToolLockfileSentinel())
    tool_classpath, config_files = await MultiGet(
        Get(ToolClasspath, ToolClasspathRequest(lockfile=lockfile_request)),
        Get(ScalafixConfigFiles, GatherScalafixConfigFilesRequest(filepaths)),
    )

    extra_immutable_input_digests = {toolcp_relpath: tool_classpath.digest}

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

    def combine_classpaths(classpaths: Iterable[Classpath]) -> Classpath:
        classpath_entries: set[ClasspathEntry] = set()
        # Requires type annotation due to https://github.com/python/mypy/issues/5423
        resolve_key: Optional[CoursierResolveKey] = None
        for clspath in classpaths:
            if resolve_key is None:
                resolve_key = clspath.resolve
            elif resolve_key != clspath.resolve:
                raise ValueError("Can not combine classpaths for different resolves.")

            classpath_entries.update(clspath.entries)

        assert resolve_key
        return Classpath(tuple(classpath_entries), resolve_key)

    def classpath_for_files(files: Iterable[str]) -> Classpath:
        classpaths_to_combine: set[Classpath] = set()
        for file in files:
            filepath = PurePath(file)
            for path_pattern, classpath in classpath_by_filepath.items():
                if filepath.match(path_pattern):
                    classpaths_to_combine.add(classpath)

        return combine_classpaths(classpaths_to_combine)

    def partition_info_for(files: Iterable[str], config_snapshot: Snapshot) -> PartitionInfo:
        classpath = classpath_for_files(files)
        return PartitionInfo(
            classpath_entries=(
                *tool_classpath.classpath_entries(toolcp_relpath),
                *classpath.immutable_inputs_args(),
            ),
            config_snapshot=config_snapshot,
            extra_immutable_input_digests=FrozenDict(
                {**extra_immutable_input_digests, **dict(classpath.immutable_inputs())}
            ),
        )

    return Partitions(
        Partition(
            tuple(files),
            partition_info_for(files, config_snapshot),
        )
        for files, config_snapshot in zip(
            source_files_by_config_file.values(), config_file_snapshots
        )
    )


@rule
async def scalafix_fix(
    request: ScalafixRequest.Batch,
    jdk: InternalJdk,
    tool: ScalafixSubsystem,
    scala: ScalaSubsystem,
    scalac: Scalac,
) -> FixResult:
    partition_info = cast(PartitionInfo, request.partition_metadata)
    merged_digest = await Get(
        Digest, MergeDigests([partition_info.config_snapshot.digest, request.snapshot.digest])
    )

    result = await Get(
        ProcessResult,
        JvmProcess(
            jdk=jdk,
            argv=[
                "scalafix.cli.Cli",
                "--verbose",
                "--config",
                partition_info.config_snapshot.files[0],
                "--scalac-options",
                *scalac.args,
                "--files",
                *request.files,
            ],
            classpath_entries=partition_info.classpath_entries,
            input_digest=merged_digest,
            output_files=request.files,
            extra_jvm_options=tool.jvm_options,
            extra_immutable_input_digests=partition_info.extra_immutable_input_digests,
            use_nailgun=False,
            description=f"Run `scalafix` on {pluralize(len(request.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )

    return await FixResult.create(request, result)


@rule
async def generate_scalafix_lockfile_request(
    _: ScalafixToolLockfileSentinel, tool: ScalafixSubsystem
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool.create(tool)


def rules():
    return [
        *collect_rules(),
        *lockfile.rules(),
        *ScalafixRequest.rules(),
        UnionRule(GenerateToolLockfileSentinel, ScalafixToolLockfileSentinel),
    ]
