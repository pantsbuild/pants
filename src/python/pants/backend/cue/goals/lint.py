# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Any, Iterable

from pants.backend.cue import subsystem
from pants.backend.cue.rules import _run_cue
from pants.backend.cue.subsystem import Cue
from pants.backend.cue.target_types import CueFieldSet
from pants.core.goals.lint import LintResult, LintTargetsRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.engine.platform import Platform
from pants.engine.rules import Rule, collect_rules, rule
from pants.util.logging import LogLevel


class CueLintRequest(LintTargetsRequest):
    field_set_type = CueFieldSet
    tool_subsystem = Cue
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


@rule(desc="Lint with cue", level=LogLevel.DEBUG)
async def run_cue_vet(
    request: CueLintRequest.Batch[CueFieldSet, Any],
    cue: Cue,
    platform: Platform,
) -> LintResult:
    sources = await determine_source_files(
        SourceFilesRequest(sources_fields=[field_set.sources for field_set in request.elements])
    )
    process_result = await _run_cue("vet", cue=cue, snapshot=sources.snapshot, platform=platform)
    return LintResult.create(request, process_result)


def rules() -> Iterable[Rule]:
    return (
        *collect_rules(),
        *CueLintRequest.rules(),
        *subsystem.rules(),
    )
