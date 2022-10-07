# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.python.lint.black import subsystem as black_subsystem
from pants.backend.python.lint.black.rules import _run_black
from pants.backend.python.lint.black.subsystem import Black
from pants.core.goals.fmt import FmtFilesRequest, FmtResult, Partitions
from pants.engine.internals.build_files import BuildFileOptions
from pants.engine.rules import collect_rules, rule
from pants.source.filespec import FilespecMatcher
from pants.util.logging import LogLevel


class BlackRequest(FmtFilesRequest):
    tool_subsystem = Black


@rule
async def partition_build_files(
    request: BlackRequest.PartitionRequest,
    black: Black,
    build_file_options: BuildFileOptions,
) -> Partitions:
    if black.skip:
        return Partitions()

    specified_build_files = FilespecMatcher(
        includes=[os.path.join("**", p) for p in build_file_options.patterns],
        excludes=build_file_options.ignores,
    ).matches(request.files)

    return Partitions.single_partition(specified_build_files)


@rule(desc="Format with Black", level=LogLevel.DEBUG)
async def black_fmt(request: BlackRequest.SubPartition, black: Black) -> FmtResult:
    black_ics = await Black._find_python_interpreter_constraints_from_lockfile(black)
    return await _run_black(request, black, black_ics)


def rules():
    return [
        *collect_rules(),
        *BlackRequest.rules(),
        *black_subsystem.rules(),
    ]
