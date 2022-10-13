# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript.subsystems.nodejs import NpxProcess
from pants.backend.python.target_types import PythonSourceField
from pants.backend.python.typecheck.pyright.subsystem import Pyright
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, Rule, collect_rules, rule
from pants.engine.target import FieldSet
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PyrightFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    sources: PythonSourceField


class PyrightRequest(CheckRequest):
    field_set_type = PyrightFieldSet
    tool_name = Pyright.options_scope


@rule(desc="Typecheck using Pyright", level=LogLevel.DEBUG)
async def pyright_typecheck(request: PyrightRequest, pyright: Pyright) -> CheckResults:
    if pyright.skip:
        return CheckResults([], checker_name=request.tool_name)

    source_files = await Get(
        SourceFiles, SourceFilesRequest([field_set.sources for field_set in request.field_sets])
    )

    process = await Get(
        Process,
        NpxProcess(
            npm_package=pyright.default_version,
            args=(
                *pyright.args,  # User-added arguments
                *source_files.snapshot.files,
            ),
            input_digest=source_files.snapshot.digest,
            description=f"Run Pyright on {pluralize(len(source_files.snapshot.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    result = await Get(FallibleProcessResult, Process, process)
    check_result = CheckResult.from_fallible_process_result(
        result,
    )

    return CheckResults(
        [check_result],
        checker_name=request.tool_name,
    )


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        UnionRule(CheckRequest, PyrightRequest),
    )
