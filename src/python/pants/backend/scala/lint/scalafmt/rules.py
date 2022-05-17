# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os.path
import textwrap
from collections import defaultdict
from dataclasses import dataclass

from pants.backend.scala.lint.scalafmt.skip_field import SkipScalafmtField
from pants.backend.scala.lint.scalafmt.subsystem import ScalafmtSubsystem
from pants.backend.scala.target_types import ScalaSourceField
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.core.goals.fmt import FmtRequest, FmtResult
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.goals.tailor import group_by_dir
from pants.engine.fs import (
    Digest,
    DigestSubset,
    GlobExpansionConjunction,
    MergeDigests,
    PathGlobs,
    Snapshot,
)
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.jvm.goals import lockfile
from pants.jvm.jdk_rules import InternalJdk, JvmProcess
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool
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


class ScalafmtRequest(FmtRequest):
    field_set_type = ScalafmtFieldSet
    name = ScalafmtSubsystem.options_scope


class ScalafmtToolLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = ScalafmtSubsystem.options_scope


@dataclass(frozen=True)
class Partition:
    process: JvmProcess
    description: str


@dataclass(frozen=True)
class Setup:
    partitions: tuple[Partition, ...]
    original_snapshot: Snapshot


@dataclass(frozen=True)
class GatherScalafmtConfigFilesRequest:
    snapshot: Snapshot


@dataclass(frozen=True)
class ScalafmtConfigFiles:
    snapshot: Snapshot
    source_dir_to_config_file: FrozenDict[str, str]


@dataclass(frozen=True)
class SetupScalafmtPartition:
    classpath_entries: tuple[str, ...]
    merged_sources_digest: Digest
    extra_immutable_input_digests: FrozenDict[str, Digest]
    config_file: str
    files: tuple[str, ...]


def find_nearest_ancestor_file(files: set[str], dir: str, config_file: str) -> str | None:
    while True:
        candidate_config_file_path = os.path.join(dir, config_file)
        if candidate_config_file_path in files:
            return candidate_config_file_path

        if dir == "":
            return None
        dir = os.path.dirname(dir)


@rule
async def gather_scalafmt_config_files(
    request: GatherScalafmtConfigFilesRequest,
) -> ScalafmtConfigFiles:
    """Gather scalafmt config files and identify which config files to use for each source
    directory."""
    source_dirs = frozenset(os.path.dirname(path) for path in request.snapshot.files)

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
async def setup_scalafmt_partition(
    request: SetupScalafmtPartition,
    jdk: InternalJdk,
) -> Partition:
    sources_digest = await Get(
        Digest,
        DigestSubset(
            request.merged_sources_digest,
            PathGlobs(
                [request.config_file, *request.files],
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                conjunction=GlobExpansionConjunction.all_match,
                description_of_origin=f"the files in scalafmt partition for config file {request.config_file}",
            ),
        ),
    )

    args = [
        "org.scalafmt.cli.Cli",
        f"--config={request.config_file}",
        "--non-interactive",
    ]
    args.extend(request.files)

    process = JvmProcess(
        jdk=jdk,
        argv=args,
        classpath_entries=request.classpath_entries,
        input_digest=sources_digest,
        output_files=request.files,
        extra_immutable_input_digests=request.extra_immutable_input_digests,
        # extra_nailgun_keys=request.extra_immutable_input_digests,
        use_nailgun=False,
        description=f"Run `scalafmt` on {pluralize(len(request.files), 'file')}.",
        level=LogLevel.DEBUG,
    )

    return Partition(process, f"{pluralize(len(request.files), 'file')} ({request.config_file})")


@rule(level=LogLevel.DEBUG)
async def setup_scalafmt(
    request: ScalafmtRequest,
) -> Setup:
    toolcp_relpath = "__toolcp"

    lockfile_request = await Get(GenerateJvmLockfileFromTool, ScalafmtToolLockfileSentinel())
    tool_classpath, config_files = await MultiGet(
        Get(ToolClasspath, ToolClasspathRequest(lockfile=lockfile_request)),
        Get(ScalafmtConfigFiles, GatherScalafmtConfigFilesRequest(request.snapshot)),
    )

    merged_sources_digest = await Get(
        Digest, MergeDigests([request.snapshot.digest, config_files.snapshot.digest])
    )

    extra_immutable_input_digests = {
        toolcp_relpath: tool_classpath.digest,
    }

    # Partition the work by which source files share the same config file (regardless of directory).
    source_files_by_config_file: dict[str, set[str]] = defaultdict(set)
    for source_dir, files_in_source_dir in group_by_dir(request.snapshot.files).items():
        config_file = config_files.source_dir_to_config_file[source_dir]
        source_files_by_config_file[config_file].update(
            os.path.join(source_dir, name) for name in files_in_source_dir
        )

    partitions = await MultiGet(
        Get(
            Partition,
            SetupScalafmtPartition(
                classpath_entries=tuple(tool_classpath.classpath_entries(toolcp_relpath)),
                merged_sources_digest=merged_sources_digest,
                extra_immutable_input_digests=FrozenDict(extra_immutable_input_digests),
                config_file=config_file,
                files=tuple(sorted(files)),
            ),
        )
        for config_file, files in source_files_by_config_file.items()
    )

    return Setup(tuple(partitions), original_snapshot=request.snapshot)


@rule(desc="Format with scalafmt", level=LogLevel.DEBUG)
async def scalafmt_fmt(request: ScalafmtRequest, tool: ScalafmtSubsystem) -> FmtResult:
    if tool.skip:
        return FmtResult.skip(formatter_name=request.name)
    setup = await Get(Setup, ScalafmtRequest, request)
    results = await MultiGet(
        Get(ProcessResult, JvmProcess, partition.process) for partition in setup.partitions
    )

    def format(description: str, output) -> str:
        if len(output.strip()) == 0:
            return ""

        return textwrap.dedent(
            f"""\
        Output from `scalafmt` on {description}:
        {output.decode("utf-8")}

        """
        )

    stdout_content = ""
    stderr_content = ""
    for partition, result in zip(setup.partitions, results):
        stdout_content += format(partition.description, result.stdout)
        stderr_content += format(partition.description, result.stderr)

    # Merge all of the outputs into a single output.
    output_digest = await Get(Digest, MergeDigests([r.output_digest for r in results]))
    output_snapshot = await Get(Snapshot, Digest, output_digest)

    fmt_result = FmtResult(
        input=setup.original_snapshot,
        output=output_snapshot,
        stdout=stdout_content,
        stderr=stderr_content,
        formatter_name=request.name,
    )
    return fmt_result


@rule
def generate_scalafmt_lockfile_request(
    _: ScalafmtToolLockfileSentinel, tool: ScalafmtSubsystem
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool.create(tool)


def rules():
    return [
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(FmtRequest, ScalafmtRequest),
        UnionRule(GenerateToolLockfileSentinel, ScalafmtToolLockfileSentinel),
    ]
