# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.build_files.fmt.base import FmtBuildFilesRequest
from pants.backend.python.lint.black import subsystem as black_subsystem
from pants.backend.python.lint.black.rules import _run_black
from pants.backend.python.lint.black.subsystem import Black
from pants.backend.python.subsystems.python_tool_base import get_lockfile_interpreter_constraints
from pants.core.goals.fmt import FmtResult
from pants.engine.rules import collect_rules, rule
from pants.util.logging import LogLevel


class BlackRequest(FmtBuildFilesRequest):
    tool_subsystem = Black


@rule(desc="Format with Black", level=LogLevel.DEBUG)
async def black_fmt(request: BlackRequest.Batch, black: Black) -> FmtResult:
    black_ics = await get_lockfile_interpreter_constraints(black)
    return await _run_black(request, black, black_ics)


def rules():
    return [
        *collect_rules(),
        *BlackRequest.rules(),
        *black_subsystem.rules(),
    ]
