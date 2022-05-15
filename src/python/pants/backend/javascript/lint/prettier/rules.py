# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript.lint.prettier.subsystem import Prettier
from pants.backend.javascript.subsystems.nodejs import DownloadedNpxTool, NpxToolRequest
from pants.backend.javascript.target_types import JSSourceField
from pants.core.goals.fmt import FmtRequest, FmtResult
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.engine.fs import Digest, MergeDigests, Snapshot
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, Rule, collect_rules, rule
from pants.engine.target import FieldSet
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PrettierFmtFieldSet(FieldSet):
    required_fields = (JSSourceField,)

    sources: JSSourceField


class PrettierFmtRequest(FmtRequest):
    field_set_type = PrettierFmtFieldSet
    name = Prettier.options_scope


@rule(level=LogLevel.DEBUG)
async def prettier_fmt(request: PrettierFmtRequest, prettier: Prettier) -> FmtResult:
    if prettier.skip:
        return FmtResult.skip(formatter_name=request.name)

    prettier_tool_get = Get(DownloadedNpxTool, NpxToolRequest, prettier.get_request())

    # Look for any/all of the Prettier configuration files
    config_files_get = Get(
        ConfigFiles,
        ConfigFilesRequest,
        prettier.config_request(request.snapshot.dirs),
    )

    prettier_tool, config_files = await MultiGet(prettier_tool_get, config_files_get)

    # Merge source files, config files, and prettier_tool process
    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                request.snapshot.digest,
                config_files.snapshot.digest,
                prettier_tool.digest,
            )
        ),
    )

    logger.warning(prettier_tool.exe)
    argv = [
        *prettier_tool.exe.split(" "),
        "--write",
        *request.snapshot.files,
    ]

    result = await Get(
        ProcessResult,
        Process(
            argv=argv,
            input_digest=input_digest,
            output_files=request.snapshot.files,
            description=f"Run Prettier on {pluralize(len(request.snapshot.files), 'file')}.",
            level=LogLevel.DEBUG,
            env=prettier_tool.env,
        ),
    )
    output_snapshot = await Get(Snapshot, Digest, result.output_digest)
    return FmtResult.create(request, result, output_snapshot, strip_chroot_path=True)


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        UnionRule(FmtRequest, PrettierFmtRequest),
    )
