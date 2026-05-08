# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
from dataclasses import dataclass
from pathlib import PurePath
from typing import AbstractSet, Any

from pants.backend.python.lint.ruff.check.skip_field import SkipRuffCheckField
from pants.backend.python.lint.ruff.common import RunRuffRequest, run_ruff
from pants.backend.python.lint.ruff.skip_field import SkipRuffField
from pants.backend.python.lint.ruff.subsystem import Ruff, RuffMode
from pants.backend.python.target_types import (
    InterpreterConstraintsField,
    PythonResolveField,
    PythonSourceField,
)
from pants.backend.python.util_rules import pex
from pants.core.goals.fix import FixResult, FixTargetsRequest
from pants.core.goals.lint import REPORT_DIR, LintResult, LintTargetsRequest
from pants.core.util_rules.partitions import Partition, PartitionerType, Partitions
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.engine.fs import (
    CreateDigest,
    DigestSubset,
    FileContent,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
)
from pants.engine.internals.graph import resolve_source_paths
from pants.engine.intrinsics import (
    create_digest,
    digest_subset_to_digest,
    digest_to_snapshot,
    merge_digests,
    remove_prefix,
)
from pants.engine.platform import Platform
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import FieldSet, SourcesPathsRequest, Target
from pants.util.logging import LogLevel
from pants.util.meta import classproperty


@dataclass(frozen=True)
class RuffCheckFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField
    resolve: PythonResolveField
    interpreter_constraints: InterpreterConstraintsField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipRuffCheckField).value or tgt.get(SkipRuffField).value


class RuffLintRequest(LintTargetsRequest):
    field_set_type = RuffCheckFieldSet
    tool_subsystem = Ruff  # type: ignore[assignment]
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION

    @classproperty
    def tool_name(cls) -> str:
        return "ruff check"

    @classproperty
    def tool_id(cls) -> str:
        return "ruff-check"


class RuffFixRequest(FixTargetsRequest):
    field_set_type = RuffCheckFieldSet
    tool_subsystem = Ruff  # type: ignore[assignment]
    partitioner_type = PartitionerType.CUSTOM

    # We don't need to include automatically added lint rules for this RuffFixRequest,
    # because these lint rules are already checked by RuffLintRequest.
    enable_lint_rules = False

    @classproperty
    def tool_name(cls) -> str:
        return "ruff check --fix"

    @classproperty
    def tool_id(cls) -> str:
        return RuffLintRequest.tool_id


@dataclass(frozen=True)
class RuffFixPartitionMetadata:
    init_files: tuple[str, ...]

    @property
    def description(self) -> None:
        return None


def _ancestor_init_files(
    files: tuple[str, ...], candidate_init_files: AbstractSet[str]
) -> tuple[str, ...]:
    init_files = set[str]()
    for file in files:
        for directory in [parent for parent in PurePath(file).parents if str(parent) != "."]:
            init_file = str(directory / "__init__.py")
            if init_file in candidate_init_files:
                init_files.add(init_file)
    return tuple(sorted(init_files))


@rule
async def partition_ruff_fix(
    request: RuffFixRequest.PartitionRequest, ruff: Ruff
) -> Partitions[str, RuffFixPartitionMetadata]:
    if ruff.skip:
        return Partitions()

    all_sources_paths = await concurrently(
        resolve_source_paths(SourcesPathsRequest(field_set.source), **implicitly())
        for field_set in request.field_sets
    )
    files = tuple(
        sorted(
            itertools.chain.from_iterable(
                sources_paths.files for sources_paths in all_sources_paths
            )
        )
    )
    selected_init_files = {file for file in files if PurePath(file).name == "__init__.py"}
    metadata = RuffFixPartitionMetadata(_ancestor_init_files(files, selected_init_files))

    return Partitions([Partition(files, metadata)])


@rule(desc="Fix with `ruff check --fix`", level=LogLevel.DEBUG)
async def ruff_fix(request: RuffFixRequest.Batch, ruff: Ruff, platform: Platform) -> FixResult:
    # Ruff's isort rules use package marker files to classify imports. The `fix` goal may split
    # editable files into smaller batches, so reconstruct selected ancestor `__init__.py` files as
    # read-only context while still asking Ruff to edit only the current batch.
    init_files = (
        request.partition_metadata.init_files
        if isinstance(request.partition_metadata, RuffFixPartitionMetadata)
        else ()
    )
    missing_init_files = tuple(file for file in init_files if file not in request.snapshot.files)
    init_digest = await create_digest(
        CreateDigest(FileContent(file, b"") for file in missing_init_files)
    )
    snapshot = await digest_to_snapshot(
        await merge_digests(MergeDigests((request.snapshot.digest, init_digest)))
    )
    result = await run_ruff(
        RunRuffRequest(snapshot=snapshot, files=request.files, mode=RuffMode.FIX),
        ruff,
        platform,
    )
    return await FixResult.create(request, result)


@rule(desc="Lint with `ruff check`", level=LogLevel.DEBUG)
async def ruff_lint(
    request: RuffLintRequest.Batch[RuffCheckFieldSet, Any],
    ruff: Ruff,
    platform: Platform,
) -> LintResult:
    source_files = await determine_source_files(
        SourceFilesRequest(field_set.source for field_set in request.elements)
    )
    result = await run_ruff(
        RunRuffRequest(
            snapshot=source_files.snapshot,
            files=source_files.snapshot.files,
            mode=RuffMode.LINT,
        ),
        ruff,
        platform,
    )
    report_digest = await digest_subset_to_digest(
        DigestSubset(result.output_digest, PathGlobs([f"{REPORT_DIR}/**"]))
    )
    report = await remove_prefix(RemovePrefix(report_digest, REPORT_DIR))
    return LintResult.create(request, result, report=report)


def rules():
    return (
        *collect_rules(),
        *RuffFixRequest.rules(),
        *RuffLintRequest.rules(),
        *pex.rules(),
    )
