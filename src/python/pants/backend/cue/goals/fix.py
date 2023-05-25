# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.backend.cue.rules import _run_cue
from pants.backend.cue.subsystem import Cue
from pants.backend.cue.target_types import CueFieldSet
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.platform import Platform
from pants.engine.rules import collect_rules, rule
from pants.util.logging import LogLevel


class CueFmtRequest(FmtTargetsRequest):
    field_set_type = CueFieldSet
    tool_subsystem = Cue
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


@rule(desc="Format with cue", level=LogLevel.DEBUG)
async def run_cue_fmt(request: CueFmtRequest.Batch, cue: Cue, platform: Platform) -> FmtResult:
    process_result = await _run_cue(
        "fmt",
        cue=cue,
        snapshot=request.snapshot,
        platform=platform,
        output_files=request.snapshot.files,
    )
    return await FmtResult.create(request, process_result)


def rules():
    return [
        *collect_rules(),
        *CueFmtRequest.rules(),
    ]
