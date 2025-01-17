# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.build_files.fmt.base import FmtBuildFilesRequest
from pants.backend.python.lint.ruff import subsystem as ruff_subsystem
from pants.backend.python.lint.ruff.format import rules as ruff_format_backend
from pants.backend.python.lint.ruff.format.rules import _run_ruff_fmt
from pants.backend.python.lint.ruff.subsystem import Ruff
from pants.core.goals.fmt import FmtResult
from pants.engine.platform import Platform
from pants.engine.rules import collect_rules, rule
from pants.util.logging import LogLevel


class RuffRequest(FmtBuildFilesRequest):
    tool_subsystem = Ruff


@rule(desc="Format with Ruff", level=LogLevel.DEBUG)
async def ruff_fmt(request: RuffRequest.Batch, ruff: Ruff, platform: Platform) -> FmtResult:
    return await _run_ruff_fmt(request, ruff, platform)


def rules():
    return [
        *collect_rules(),
        *RuffRequest.rules(),
        *ruff_format_backend.rules(),
        *ruff_subsystem.rules(),
    ]
