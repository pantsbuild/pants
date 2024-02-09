# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.build_files.fmt.base import FmtBuildFilesRequest
from pants.backend.python.lint.ruff import subsystem as ruff_subsystem
from pants.backend.python.lint.ruff.rules import _run_ruff_fmt
from pants.backend.python.lint.ruff.subsystem import Ruff
from pants.backend.python.subsystems.python_tool_base import get_lockfile_interpreter_constraints
from pants.core.goals.fmt import FmtResult
from pants.engine.rules import collect_rules, rule
from pants.util.logging import LogLevel


class RuffRequest(FmtBuildFilesRequest):
    tool_subsystem = Ruff


@rule(desc="Format with Ruff", level=LogLevel.DEBUG)
async def ruff_fmt(request: RuffRequest.Batch, ruff: Ruff) -> FmtResult:
    ruff_ics = await get_lockfile_interpreter_constraints(ruff)
    return await _run_ruff_fmt(request, ruff, ruff_ics)


def rules():
    return [
        *collect_rules(),
        *RuffRequest.rules(),
        *ruff_subsystem.rules(),
    ]
