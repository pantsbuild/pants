# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
import textwrap
from dataclasses import dataclass
from typing import Any, cast

from pants.backend.terraform.partition import partition_files_by_directory
from pants.backend.terraform.target_types import TerraformFieldSet
from pants.backend.terraform.tool import TerraformProcess
from pants.backend.terraform.tool import rules as tool_rules
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest
from pants.core.util_rules import external_tool
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.internals.native_engine import Snapshot
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.subsystem import GoalToolMixin, Subsystem
from pants.util.frozendict import FrozenDict
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


class TfFmtSubsystem(GoalToolMixin, Subsystem):
    options_scope = "terraform-fmt"
    name = "`terraform fmt`"
    example_goal_name = "fmt"
    help = "Terraform fmt options."


class TffmtRequest(FmtTargetsRequest):
    field_set_type = TerraformFieldSet
    name = TfFmtSubsystem.options_scope


@dataclass(frozen=True)
class TffmtPartitionRequest:
    field_sets: tuple[TerraformFieldSet, ...]


class TffmtPartitions(FrozenDict[Any, "tuple[str, ...]"]):
    pass


@dataclass(frozen=True)
class TffmtSubPartitionRequest:
    files: tuple[str, ...]
    key: Any
    snapshot: Snapshot  # NB: May contain more files than `files`


@rule
async def partition_tffmt(request: TffmtPartitionRequest, tffmt: TfFmtSubsystem) -> TffmtPartitions:
    source_files = await Get(
        SourceFiles, SourceFilesRequest([field_set.sources for field_set in request.field_sets])
    )

    return TffmtPartitions(
        (directory, tuple(files))
        for directory, files in partition_files_by_directory(source_files.files).items()
    )


@rule
async def run_tffmt(request: TffmtSubPartitionRequest) -> ProcessResult:
    directory = cast(str, request.key)
    snapshot = request.snapshot

    result = await Get(
        ProcessResult,
        TerraformProcess(
            args=("fmt", directory),
            input_digest=snapshot.digest,
            output_files=request.files,
            description=f"Run `terraform fmt` on {pluralize(len(request.files), 'file')}.",
        ),
    )

    return result


@rule(desc="Format with `terraform fmt`")
async def tffmt_fmt(request: TffmtRequest, tffmt: TfFmtSubsystem) -> FmtResult:
    if tffmt.skip:
        return FmtResult.skip(formatter_name=request.name)

    partitions = await Get(TffmtPartitions, TffmtPartitionRequest(request.field_sets))
    results = await MultiGet(
        Get(ProcessResult, TffmtSubPartitionRequest(files, key, request.snapshot))
        for key, files in partitions.items()
    )

    def format(directory, output):
        if len(output.strip()) == 0:
            return ""

        return textwrap.dedent(
            f"""\
        Output from `terraform fmt` on files in {directory}:
        {output.decode("utf-8")}

        """
        )

    stdout_content = ""
    stderr_content = ""
    for directory, result in zip(partitions, results):
        stdout_content += format(directory, result.stdout)
        stderr_content += format(directory, result.stderr)

    # Merge all of the outputs into a single output.
    output_digest = await Get(Digest, MergeDigests(r.output_digest for r in results))
    output_snapshot = await Get(Snapshot, Digest, output_digest)

    fmt_result = FmtResult(
        input=request.snapshot,
        output=output_snapshot,
        stdout=stdout_content,
        stderr=stderr_content,
        formatter_name=request.name,
    )
    return fmt_result


def rules():
    return [
        *collect_rules(),
        *external_tool.rules(),
        *tool_rules(),
        UnionRule(FmtTargetsRequest, TffmtRequest),
    ]
