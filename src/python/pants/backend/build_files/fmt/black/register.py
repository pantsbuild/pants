# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.lint.black import subsystem as black_subsystem
from pants.backend.python.lint.black.rules import _run_black
from pants.backend.python.lint.black.subsystem import Black
from pants.core.goals.fmt import FmtResult, _FmtBuildFilesRequest
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


class BlackRequest(_FmtBuildFilesRequest):
    name = "black"


@rule(desc="Format with Black", level=LogLevel.DEBUG)
async def black_fmt(request: BlackRequest, black: Black) -> FmtResult:
    black_ics = await Black._find_python_interpreter_constraints_from_lockfile(black)
    return await _run_black(request, black, black_ics)


def rules():
    return [
        *collect_rules(),
        UnionRule(_FmtBuildFilesRequest, BlackRequest),
        *black_subsystem.rules(),
    ]
