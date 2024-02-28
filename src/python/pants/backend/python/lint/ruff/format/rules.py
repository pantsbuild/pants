# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional

from pants.backend.python.lint.ruff.common import RunRuffRequest, run_ruff
from pants.backend.python.lint.ruff.format.skip_field import SkipRuffFormatField
from pants.backend.python.lint.ruff.subsystem import Ruff, RuffMode
from pants.backend.python.target_types import (
    InterpreterConstraintsField,
    PythonResolveField,
    PythonSourceField,
)
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.goals.fmt import AbstractFmtRequest, FmtResult, FmtTargetsRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.util.logging import LogLevel
from pants.util.meta import classproperty


@dataclass(frozen=True)
class RuffFormatFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField
    resolve: PythonResolveField
    interpreter_constraints: InterpreterConstraintsField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipRuffFormatField).value


class RuffFormatRequest(FmtTargetsRequest):
    field_set_type = RuffFormatFieldSet
    tool_subsystem = Ruff
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION

    @classproperty
    def tool_name(cls) -> str:
        return "ruff format"

    @classproperty
    def tool_id(self) -> str:
        return "ruff-format"


# Note - this function is kept separate because it is invoked from update_build_files.py, but
# not as a rule.
async def _run_ruff_fmt(
    request: AbstractFmtRequest.Batch,
    ruff: Ruff,
    interpreter_constraints: Optional[InterpreterConstraints] = None,
) -> FmtResult:
    run_ruff_request = RunRuffRequest(
        snapshot=request.snapshot,
        mode=RuffMode.FORMAT,
        interpreter_constraints=interpreter_constraints,
    )
    result = await run_ruff(run_ruff_request, ruff)
    return await FmtResult.create(request, result)


@rule(desc="Format with `ruff format`", level=LogLevel.DEBUG)
async def ruff_fmt(request: RuffFormatRequest.Batch, ruff: Ruff) -> FmtResult:
    return await _run_ruff_fmt(request, ruff)


def rules():
    return [
        *collect_rules(),
        *RuffFormatRequest.rules(),
        *pex.rules(),
    ]
