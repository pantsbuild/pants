# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pants.backend.cue.subsystem import Cue
from pants.backend.cue.target_types import CuePackageSourcesField
from pants.core.goals.lint import LintResult, LintTargetsRequest
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class CueFieldSet(FieldSet):
    required_fields = (CuePackageSourcesField,)

    sources: CuePackageSourcesField


class CueLintRequest(LintTargetsRequest):
    field_set_type = CueFieldSet
    tool_subsystem = Cue
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


def generate_argv(*args: str, sources: SourceFiles, cue: Cue) -> tuple[str, ...]:
    return args + cue.args + sources.snapshot.files


@rule(desc="Lint CUE files", level=LogLevel.DEBUG)
async def run_cue_vet(
    request: CueLintRequest.Batch[CueFieldSet, Any],
    cue: Cue,
    platform: Platform,
) -> LintResult:
    downloaded_cue, sources = await MultiGet(
        Get(DownloadedExternalTool, ExternalToolRequest, cue.get_request(platform)),
        Get(
            SourceFiles,
            SourceFilesRequest(
                sources_fields=[field_set.sources for field_set in request.elements]
            ),
        ),
    )
    input_digest = await Get(Digest, MergeDigests((downloaded_cue.digest, sources.snapshot.digest)))
    process_result = await Get(
        FallibleProcessResult,
        Process(
            argv=[downloaded_cue.exe, *generate_argv("vet", sources=sources, cue=cue)],
            input_digest=input_digest,
            description=f"Run `cue vet` on {pluralize(len(sources.snapshot.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )

    return LintResult.create(request, process_result)


def rules():
    return [
        *collect_rules(),
        *CueLintRequest.rules(),
    ]
