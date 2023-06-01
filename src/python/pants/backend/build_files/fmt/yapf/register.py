# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.build_files.fmt.base import FmtBuildFilesRequest
from pants.backend.python.lint.yapf import subsystem as yapf_subsystem
from pants.backend.python.lint.yapf.rules import _run_yapf
from pants.backend.python.lint.yapf.subsystem import Yapf
from pants.backend.python.subsystems.python_tool_base import get_lockfile_interpreter_constraints
from pants.core.goals.fmt import FmtResult
from pants.engine.rules import collect_rules, rule
from pants.util.logging import LogLevel


class YapfRequest(FmtBuildFilesRequest):
    tool_subsystem = Yapf


@rule(desc="Format with Yapf", level=LogLevel.DEBUG)
async def yapf_fmt(request: YapfRequest.Batch, yapf: Yapf) -> FmtResult:
    yapf_ics = await get_lockfile_interpreter_constraints(yapf)
    return await _run_yapf(request, yapf, yapf_ics)


def rules():
    return [
        *collect_rules(),
        *YapfRequest.rules(),
        *yapf_subsystem.rules(),
    ]
