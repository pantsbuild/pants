# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript.lint.prettier.subsystem import Prettier
from pants.backend.javascript.subsystems.nodejs import NpxProcess
from pants.backend.javascript.target_types import JSSourceField
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest, Partitions
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.engine.fs import Digest, MergeDigests, Snapshot
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
    tool_name = Prettier.options_scope


@rule
async def partition_prettier(
    request: PrettierFmtRequest.PartitionRequest, prettier: Prettier
) -> Partitions:
    return (
        Partitions()
        if prettier.skip
        else Partitions.single_partition(
            field_set.sources.file_path for field_set in request.field_sets
        )
    )


@rule(level=LogLevel.DEBUG)
async def prettier_fmt(request: PrettierFmtRequest.SubPartition, prettier: Prettier) -> FmtResult:
    snapshot = await PrettierFmtRequest.SubPartition.get_snapshot(request)

    # Look for any/all of the Prettier configuration files
    config_files = await Get(
        ConfigFiles,
        ConfigFilesRequest,
        prettier.config_request(snapshot.dirs),
    )

    # Merge source files, config files, and prettier_tool process
    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                snapshot.digest,
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
                *snapshot.files,
            ),
            input_digest=input_digest,
            output_files=snapshot.files,
            description=f"Run Prettier on {pluralize(len(request.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    output_snapshot = await Get(Snapshot, Digest, result.output_digest)
    return FmtResult.create(
        result,
        snapshot,
        output_snapshot,
        strip_chroot_path=True,
        formatter_name=PrettierFmtRequest.tool_name,
    )


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        *PrettierFmtRequest.registration_rules(),
    )
