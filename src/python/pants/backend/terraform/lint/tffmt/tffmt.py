# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import cast

from pants.backend.terraform.partition import partition_files_by_directory
from pants.backend.terraform.target_types import TerraformFieldSet
from pants.backend.terraform.tool import TerraformProcess
from pants.backend.terraform.tool import rules as tool_rules
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest, Partitions
from pants.core.util_rules import external_tool
from pants.core.util_rules.partitions import Partition
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.internals.selectors import Get
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


class TfFmtSubsystem(Subsystem):
    options_scope = "terraform-fmt"
    name = "`terraform fmt`"
    help = "Terraform fmt options."

    skip = SkipOption("fmt", "lint")


class TffmtRequest(FmtTargetsRequest):
    field_set_type = TerraformFieldSet
    tool_subsystem = TfFmtSubsystem


@dataclass(frozen=True)
class PartitionMetadata:
    directory: str

    @property
    def description(self) -> str:
        return self.directory


@rule
async def partition_tffmt(
    request: TffmtRequest.PartitionRequest, tffmt: TfFmtSubsystem
) -> Partitions:
    if tffmt.skip:
        return Partitions()

    source_files = await Get(
        SourceFiles, SourceFilesRequest([field_set.sources for field_set in request.field_sets])
    )

    return Partitions(
        Partition(tuple(files), PartitionMetadata(directory))
        for directory, files in partition_files_by_directory(source_files.files).items()
    )


@rule(desc="Format with `terraform fmt`")
async def tffmt_fmt(request: TffmtRequest.Batch, tffmt: TfFmtSubsystem) -> FmtResult:
    directory = cast(PartitionMetadata, request.partition_metadata).directory
    result = await Get(
        ProcessResult,
        TerraformProcess(
            args=("fmt", directory),
            input_digest=request.snapshot.digest,
            output_files=request.files,
            description=f"Run `terraform fmt` on {pluralize(len(request.files), 'file')}.",
        ),
    )

    return await FmtResult.create(request, result)


def rules():
    return [
        *collect_rules(),
        *external_tool.rules(),
        *tool_rules(),
        *TffmtRequest.rules(),
    ]
