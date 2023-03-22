# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.javascript.subsystems.nodejs import NodeJSToolProcess
from pants.backend.openapi.lint.openapi_format.subsystem import (
    OpenApiFormatFieldSet,
    OpenApiFormatSubsystem,
)
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


class OpenApiFormatRequest(FmtTargetsRequest):
    field_set_type = OpenApiFormatFieldSet
    tool_subsystem = OpenApiFormatSubsystem
    partitioner_type = PartitionerType.DEFAULT_ONE_PARTITION_PER_INPUT


@rule(desc="Format with openapi-format", level=LogLevel.DEBUG)
async def run_openapi_format(
    request: OpenApiFormatRequest.Batch,
    openapi_format: OpenApiFormatSubsystem,
) -> FmtResult:
    result = await Get(
        ProcessResult,
        NodeJSToolProcess,
        NodeJSToolProcess.npx(
            npm_package=openapi_format.version,
            args=(
                *openapi_format.args,
                request.snapshot.files[0],
                "--output",
                request.snapshot.files[0],
            ),
            input_digest=request.snapshot.digest,
            output_files=request.snapshot.files,
            description=f"Run openapi-format on {pluralize(len(request.snapshot.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )

    return await FmtResult.create(request, result, strip_chroot_path=True)


def rules():
    return [
        *collect_rules(),
        *OpenApiFormatRequest.rules(),
    ]
