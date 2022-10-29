# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript.lint.prettier.subsystem import Prettier
from pants.backend.javascript.subsystems.nodejs import NpxProcess
from pants.backend.javascript.target_types import JSSourceField
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.fs import Digest, MergeDigests
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, Rule, collect_rules, rule
from pants.engine.target import FieldSet
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PrettierFmtFieldSet(FieldSet):
    required_fields = (JSSourceField,)

    sources: JSSourceField


class PrettierFmtRequest(FmtTargetsRequest):
    field_set_type = PrettierFmtFieldSet
    tool_subsystem = Prettier
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


@rule(level=LogLevel.DEBUG)
async def prettier_fmt(request: PrettierFmtRequest.Batch, prettier: Prettier) -> FmtResult:

    # Look for any/all of the Prettier configuration files
    config_files = await Get(
        ConfigFiles,
        ConfigFilesRequest,
        prettier.config_request(request.snapshot.dirs),
    )

    # Merge source files, config files, and prettier_tool process
    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                request.snapshot.digest,
                config_files.snapshot.digest,
            )
        ),
    )

    result = await Get(
        ProcessResult,
        NpxProcess(
            npm_package=prettier.default_version,
            args=(
                "--write",
                *request.files,
            ),
            input_digest=input_digest,
            output_files=request.files,
            description=f"Run Prettier on {pluralize(len(request.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return await FmtResult.create(request, result, strip_chroot_path=True)


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        *PrettierFmtRequest.rules(),
    )
