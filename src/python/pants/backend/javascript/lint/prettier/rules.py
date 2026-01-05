# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass

from pants.backend.javascript.lint.prettier.subsystem import Prettier
from pants.backend.javascript.subsystems import nodejs_tool
from pants.backend.javascript.subsystems.nodejs_tool import NodeJSToolRequest
from pants.backend.javascript.target_types import JSRuntimeSourceField
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest
from pants.core.util_rules.config_files import find_config_file
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.fs import MergeDigests
from pants.engine.intrinsics import merge_digests
from pants.engine.process import execute_process_or_raise
from pants.engine.rules import Rule, collect_rules, implicitly, rule
from pants.engine.target import FieldSet
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PrettierFmtFieldSet(FieldSet):
    required_fields = (JSRuntimeSourceField,)

    sources: JSRuntimeSourceField


class PrettierFmtRequest(FmtTargetsRequest):
    field_set_type = PrettierFmtFieldSet
    tool_subsystem = Prettier  # type: ignore[assignment]
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


@rule(level=LogLevel.DEBUG)
async def prettier_fmt(request: PrettierFmtRequest.Batch, prettier: Prettier) -> FmtResult:
    # Look for any/all of the Prettier configuration files
    config_files = await find_config_file(prettier.config_request(request.snapshot.dirs))

    # Merge source files, config files, and prettier_tool process
    input_digest = await merge_digests(
        MergeDigests(
            (
                request.snapshot.digest,
                config_files.snapshot.digest,
            )
        )
    )

    result = await execute_process_or_raise(
        **implicitly(
            {
                prettier.request(
                    args=("--write", *(os.path.join("{chroot}", file) for file in request.files)),
                    input_digest=input_digest,
                    output_files=request.files,
                    description=f"Run Prettier on {pluralize(len(request.files), 'file')}.",
                    level=LogLevel.DEBUG,
                ): NodeJSToolRequest
            }
        )
    )
    return await FmtResult.create(request, result)


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        *nodejs_tool.rules(),
        *PrettierFmtRequest.rules(),
    )
