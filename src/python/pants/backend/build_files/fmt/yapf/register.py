# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.lint.yapf import subsystem as yapf_subsystem
from pants.backend.python.lint.yapf.rules import _run_yapf
from pants.backend.python.lint.yapf.subsystem import Yapf
from pants.core.goals.fmt import FmtResult, _FmtBuildFilesRequest
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


class YapfRequest(_FmtBuildFilesRequest):
    name = "yapf"


@rule(desc="Format with Yapf", level=LogLevel.DEBUG)
async def yapf_fmt(request: YapfRequest, yapf: Yapf) -> FmtResult:
    yapf_ics = await Yapf._find_python_interpreter_constraints_from_lockfile(yapf)
    return await _run_yapf(request, yapf, yapf_ics)


def rules():
    return [
        *collect_rules(),
        UnionRule(_FmtBuildFilesRequest, YapfRequest),
        *yapf_subsystem.rules(),
    ]
