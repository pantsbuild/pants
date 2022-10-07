# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.python.lint.yapf import subsystem as yapf_subsystem
from pants.backend.python.lint.yapf.rules import _run_yapf
from pants.backend.python.lint.yapf.subsystem import Yapf
from pants.core.goals.fmt import FmtFilesRequest, FmtResult, Partitions
from pants.engine.internals.build_files import BuildFileOptions
from pants.engine.rules import collect_rules, rule
from pants.source.filespec import FilespecMatcher
from pants.util.logging import LogLevel


class YapfRequest(FmtFilesRequest):
    tool_subsystem = Yapf


@rule
async def partition_build_files(
    request: YapfRequest.PartitionRequest,
    yapf: Yapf,
    build_file_options: BuildFileOptions,
) -> Partitions:
    if yapf.skip:
        return Partitions()

    specified_build_files = FilespecMatcher(
        includes=[os.path.join("**", p) for p in build_file_options.patterns],
        excludes=build_file_options.ignores,
    ).matches(request.files)

    return Partitions.single_partition(specified_build_files)


@rule(desc="Format with Yapf", level=LogLevel.DEBUG)
async def yapf_fmt(request: YapfRequest.SubPartition, yapf: Yapf) -> FmtResult:
    yapf_ics = await Yapf._find_python_interpreter_constraints_from_lockfile(yapf)
    return await _run_yapf(request, yapf, yapf_ics)


def rules():
    return [
        *collect_rules(),
        *YapfRequest.rules(),
        *yapf_subsystem.rules(),
    ]
