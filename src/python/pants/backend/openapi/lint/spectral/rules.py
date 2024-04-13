# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
from dataclasses import dataclass
from typing import Any

from pants.backend.javascript.subsystems import nodejs_tool
from pants.backend.javascript.subsystems.nodejs_tool import NodeJSToolRequest
from pants.backend.openapi.lint.spectral.skip_field import SkipSpectralField
from pants.backend.openapi.lint.spectral.subsystem import SpectralSubsystem
from pants.backend.openapi.target_types import (
    OpenApiDocumentDependenciesField,
    OpenApiDocumentField,
    OpenApiSourceField,
)
from pants.core.goals.lint import LintResult, LintTargetsRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet, Target, TransitiveTargets, TransitiveTargetsRequest
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class SpectralFieldSet(FieldSet):
    required_fields = (OpenApiDocumentField,)

    sources: OpenApiDocumentField
    dependencies: OpenApiDocumentDependenciesField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipSpectralField).value


class SpectralRequest(LintTargetsRequest):
    field_set_type = SpectralFieldSet
    tool_subsystem = SpectralSubsystem
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


@rule(desc="Lint with Spectral", level=LogLevel.DEBUG)
async def run_spectral(
    request: SpectralRequest.Batch[SpectralFieldSet, Any],
    spectral: SpectralSubsystem,
) -> LintResult:
    transitive_targets = await Get(
        TransitiveTargets,
        TransitiveTargetsRequest(field_set.address for field_set in request.elements),
    )

    all_sources_request = Get(
        SourceFiles,
        SourceFilesRequest(
            tgt[OpenApiSourceField]
            for tgt in transitive_targets.closure
            if tgt.has_field(OpenApiSourceField)
        ),
    )
    target_sources_request = Get(
        SourceFiles,
        SourceFilesRequest(
            (field_set.sources for field_set in request.elements),
            for_sources_types=(OpenApiDocumentField,),
            enable_codegen=True,
        ),
    )

    ruleset_digest_get = Get(
        Digest, CreateDigest([FileContent(".spectral.yaml", b'extends: "spectral:oas"\n')])
    )

    target_sources, all_sources, ruleset_digest = await MultiGet(
        target_sources_request, all_sources_request, ruleset_digest_get
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                target_sources.snapshot.digest,
                all_sources.snapshot.digest,
                ruleset_digest,
            )
        ),
    )

    process_result = await Get(
        FallibleProcessResult,
        NodeJSToolRequest,
        spectral.request(
            args=(
                "lint",
                "--display-only-failures",
                "--ruleset",
                ".spectral.yaml",
                *spectral.args,
                *(os.path.join("{chroot}", file) for file in target_sources.snapshot.files),
            ),
            input_digest=input_digest,
            description=f"Run Spectral on {pluralize(len(request.elements), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )

    return LintResult.create(request, process_result)


def rules():
    return [
        *collect_rules(),
        *nodejs_tool.rules(),
        *SpectralRequest.rules(),
    ]
