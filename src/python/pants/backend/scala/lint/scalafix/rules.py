# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os.path
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable, cast

from pants.backend.scala.lint.scalafix.skip_field import SkipScalafixField
from pants.backend.scala.lint.scalafix.subsystem import ScalafixSubsystem
from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.backend.scala.subsystems.scalac import Scalac
from pants.backend.scala.target_types import ScalaSourceField
from pants.backend.scala.util_rules.versions import ScalaVersion
from pants.core.goals.fix import FixResult, FixTargetsRequest, Partitions
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.goals.lint import LintResult, LintTargetsRequest
from pants.core.util_rules.config_files import (
    GatherConfigFilesByDirectoriesRequest,
    GatheredConfigFilesByDirectories,
)
from pants.core.util_rules.partitions import Partition
from pants.core.util_rules.source_files import SourceFiles
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.fs import AddPrefix, Digest, DigestSubset, MergeDigests, PathGlobs, Snapshot
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.jvm.classpath import Classpath
from pants.jvm.compile import ClasspathEntry
from pants.jvm.goals import lockfile
from pants.jvm.jdk_rules import InternalJdk, JvmProcess
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool, GenerateJvmToolLockfileSentinel
from pants.jvm.resolve.key import CoursierResolveKey
from pants.source.source_root import SourceRootsRequest, SourceRootsResult
from pants.util.dirutil import group_by_dir
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import Simplifier, pluralize


@dataclass(frozen=True)
class ScalafixFieldSet(FieldSet):
    required_fields = (ScalaSourceField,)

    source: ScalaSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipScalafixField).value


# We define one request for `fix` and another one for `lint` because scalafix supports
# rules that have not automatic resolution and which make the process fail.
#
# In those scenarios, ignoring the tool's exit code and relying on detecting changes
# in the output files doesn't give the desired behavior. So having two distinct request
# types, one for each type of operation, targets each use case individually.


class ScalafixFixRequest(FixTargetsRequest):
    field_set_type = ScalafixFieldSet
    tool_subsystem = ScalafixSubsystem


class ScalafixLintRequest(LintTargetsRequest):
    field_set_type = ScalafixFieldSet
    tool_subsystem = ScalafixSubsystem


@dataclass(frozen=True)
class ScalafixPartitionInfo:
    scala_version: ScalaVersion | None
    config_snapshot: Snapshot
    runtime_classpath_entries: tuple[str, ...]
    compile_classpath_entries: tuple[str, ...]
    rule_classpath_entries: tuple[str, ...]
    extra_immutable_input_digests: FrozenDict[str, Digest]

    @property
    def description(self) -> str:
        return self.config_snapshot.files[0]


class ScalafixToolLockfileSentinel(GenerateJvmToolLockfileSentinel):
    resolve_name = ScalafixSubsystem.options_scope


@dataclass(frozen=True)
class _ScalafixRuleClasspath:
    classpath: Classpath | None

    def args(self, *, prefix: str = "") -> Iterable[str]:
        if not self.classpath:
            return []

        return self.classpath.immutable_inputs_args(prefix=prefix)

    def immutable_inputs(self, *, prefix: str = "") -> Iterable[tuple[str, Digest]]:
        if not self.classpath:
            return []

        return self.classpath.immutable_inputs(prefix=prefix)


@rule
async def _resolve_scalafix_rule_classpath(
    scalafix: ScalafixSubsystem,
) -> _ScalafixRuleClasspath:
    if not scalafix.extra_rule_targets:
        return _ScalafixRuleClasspath(classpath=None)

    classpath = await Get(Classpath, UnparsedAddressInputs, scalafix.extra_rule_targets)
    return _ScalafixRuleClasspath(classpath)


@dataclass(frozen=True)
class _ScalafixPartitionRequest:
    field_sets: tuple[ScalafixFieldSet, ...]


@rule
async def _partition_scalafix(
    request: _ScalafixPartitionRequest,
    rule_classpath: _ScalafixRuleClasspath,
    scala: ScalaSubsystem,
    scalafix: ScalafixSubsystem,
) -> Partitions[ScalafixPartitionInfo]:
    if scalafix.skip:
        return Partitions()

    toolcp_relpath = "__toolcp"
    compilecp_relpath = "__compilecp"
    rulecp_relpath = "__rulecp"

    filepaths = tuple(field_set.source.file_path for field_set in request.field_sets)
    classpaths: Iterable[Classpath] = ()
    if scalafix.semantic_rules:
        classpaths = await MultiGet(
            Get(Classpath, Addresses([field_set.address])) for field_set in request.field_sets
        )

    classpath_by_filepath = dict(zip(filepaths, classpaths))
    lockfile_request = await Get(GenerateJvmLockfileFromTool, ScalafixToolLockfileSentinel())
    tool_classpath, config_files = await MultiGet(
        Get(ToolClasspath, ToolClasspathRequest(lockfile=lockfile_request)),
        Get(
            GatheredConfigFilesByDirectories,
            GatherConfigFilesByDirectoriesRequest(
                tool_name="scalafix",
                config_filename=scalafix.config_file_name,
                filepaths=filepaths,
                orphan_filepath_behavior=scalafix.orphan_files_behavior,
            ),
        ),
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
        resolve_key: CoursierResolveKey | None = None
        for clspath in classpaths:
            if resolve_key is None:
                resolve_key = clspath.resolve
            elif resolve_key != clspath.resolve:
                raise ValueError("Can not combine classpaths for different resolves.")
            classpath_entries.update(clspath.entries)

        assert resolve_key
        return Classpath(tuple(classpath_entries), resolve_key)

    def classpath_for_files(files: Iterable[str]) -> Classpath | None:
        classpaths_to_combine: set[Classpath] = set()
        for file in files:
            filepath = PurePath(file)
            for path_pattern, classpath in classpath_by_filepath.items():
                if filepath.match(path_pattern):
                    classpaths_to_combine.add(classpath)

        if not classpaths_to_combine:
            return None

        return combine_classpaths(classpaths_to_combine)

    def partition_info_for(
        files: Iterable[str], config_snapshot: Snapshot
    ) -> ScalafixPartitionInfo:
        classpath = classpath_for_files(files)
        return ScalafixPartitionInfo(
            scala_version=scala.version_for_resolve(classpath.resolve.name) if classpath else None,
            runtime_classpath_entries=tuple(tool_classpath.classpath_entries(toolcp_relpath)),
            compile_classpath_entries=tuple(
                classpath.immutable_inputs_args(prefix=compilecp_relpath)
            )
            if classpath
            else (),
            rule_classpath_entries=tuple(rule_classpath.args(prefix=rulecp_relpath)),
            config_snapshot=config_snapshot,
            extra_immutable_input_digests=FrozenDict(
                {
                    **extra_immutable_input_digests,
                    **(
                        dict(classpath.immutable_inputs(prefix=compilecp_relpath))
                        if classpath
                        else {}
                    ),
                    **dict(rule_classpath.immutable_inputs(prefix=rulecp_relpath)),
                }
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
def _scalafix_fix_partitions(
    request: ScalafixFixRequest.PartitionRequest[ScalafixFieldSet],
) -> _ScalafixPartitionRequest:
    return _ScalafixPartitionRequest(request.field_sets)


@rule
async def _scalafix_lint_partitions(
    request: ScalafixLintRequest.PartitionRequest[ScalafixFieldSet],
) -> _ScalafixPartitionRequest:
    return _ScalafixPartitionRequest(request.field_sets)


async def _restore_source_roots(source_roots_result: SourceRootsResult, digest: Digest) -> Snapshot:
    source_roots_to_files = defaultdict(set)
    for file, root in source_roots_result.path_to_root.items():
        source_roots_to_files[root.path].add(str(file.relative_to(root.path)))

    digest_subsets = await MultiGet(
        Get(Digest, DigestSubset(digest, PathGlobs(files)))
        for files in source_roots_to_files.values()
    )

    restored_digests = await MultiGet(
        Get(Digest, AddPrefix(digest, source_root))
        for digest, source_root in zip(digest_subsets, source_roots_to_files.keys())
    )
    return await Get(Snapshot, MergeDigests(restored_digests))


@dataclass(frozen=True)
class _ScalafixProcess:
    snapshot: Snapshot
    partition_info: ScalafixPartitionInfo
    check_only: bool


@rule
async def _run_scalafix_process(
    request: _ScalafixProcess, jdk: InternalJdk, scalac: Scalac, scalafix: ScalafixSubsystem
) -> FallibleProcessResult:
    partition_info = request.partition_info

    merged_digest = await Get(
        Digest, MergeDigests([partition_info.config_snapshot.digest, request.snapshot.digest])
    )

    return await Get(
        FallibleProcessResult,
        JvmProcess(
            jdk=jdk,
            argv=[
                "scalafix.cli.Cli",
                f"--config={partition_info.config_snapshot.files[0]}",
                *(
                    (f"--scala-version={partition_info.scala_version}",)
                    if partition_info.scala_version
                    else ()
                ),
                *(
                    (f"--classpath={':'.join(partition_info.compile_classpath_entries)}",)
                    if partition_info.compile_classpath_entries
                    else ()
                ),
                *(
                    (f"--tool-classpath={':'.join(partition_info.rule_classpath_entries)}",)
                    if partition_info.rule_classpath_entries
                    else ()
                ),
                *(("--check",) if request.check_only else ()),
                *((f"--scalac-options={arg}" for arg in scalac.args) if scalac.args else ()),
                *(f"--files={file}" for file in request.snapshot.files),
            ],
            classpath_entries=partition_info.runtime_classpath_entries,
            input_digest=merged_digest,
            output_files=request.snapshot.files,
            extra_jvm_options=scalafix.jvm_options,
            extra_immutable_input_digests=partition_info.extra_immutable_input_digests,
            use_nailgun=False,
            description=f"Run `scalafix` on {pluralize(len(request.snapshot.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )


@rule
async def scalafix_fix(request: ScalafixFixRequest.Batch) -> FixResult:
    source_roots = await Get(
        SourceRootsResult, SourceRootsRequest, SourceRootsRequest.for_files(request.snapshot.files)
    )

    # We need to strip the source files to get semantic rules find SemanticDB metadata in the classpath
    stripped_source_files = await Get(StrippedSourceFiles, SourceFiles(request.snapshot, ()))

    process_result = await Get(
        FallibleProcessResult,
        _ScalafixProcess(
            snapshot=stripped_source_files.snapshot,
            partition_info=cast(ScalafixPartitionInfo, request.partition_metadata),
            check_only=False,
        ),
    )

    # We need now to restore the source roots
    result_snapshot = await _restore_source_roots(source_roots, process_result.output_digest)
    output_simplifier = Simplifier()

    return FixResult(
        input=request.snapshot,
        output=result_snapshot,
        stdout=output_simplifier.simplify(process_result.stdout),
        stderr=output_simplifier.simplify(process_result.stderr),
        tool_name=request.tool_name,
    )


@rule
async def scalafix_lint(request: ScalafixLintRequest.Batch) -> LintResult:
    # We need to strip the source files to get semantic rules find SemanticDB metadata in the classpath
    source_snapshot = await Get(Snapshot, PathGlobs(request.elements))
    stripped_source_files = await Get(StrippedSourceFiles, SourceFiles(source_snapshot, ()))

    process_result = await Get(
        FallibleProcessResult,
        _ScalafixProcess(
            snapshot=stripped_source_files.snapshot,
            partition_info=cast(ScalafixPartitionInfo, request.partition_metadata),
            check_only=True,
        ),
    )

    return LintResult.create(request, process_result)


@rule
async def generate_scalafix_lockfile_request(
    _: ScalafixToolLockfileSentinel, tool: ScalafixSubsystem
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool.create(tool)


def rules():
    return [
        *collect_rules(),
        *lockfile.rules(),
        *ScalafixFixRequest.rules(),
        *ScalafixLintRequest.rules(),
        UnionRule(GenerateToolLockfileSentinel, ScalafixToolLockfileSentinel),
    ]
