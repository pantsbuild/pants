# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.python.lint.pyupgrade.skip_field import SkipPyUpgradeField
from pants.backend.python.lint.pyupgrade.subsystem import PyUpgrade
from pants.backend.python.target_types import PythonSourceField
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.fix import FixResult, FixTargetsRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class PyUpgradeFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipPyUpgradeField).value


class PyUpgradeRequest(FixTargetsRequest):
    field_set_type = PyUpgradeFieldSet
    tool_subsystem = PyUpgrade
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


@rule(desc="Fix with pyupgrade", level=LogLevel.DEBUG)
async def pyupgrade_fix(request: PyUpgradeRequest.Batch, pyupgrade: PyUpgrade) -> FixResult:
    pyupgrade_pex = await Get(VenvPex, PexRequest, pyupgrade.to_pex_request())

    result = await Get(
        FallibleProcessResult,
        VenvPexProcess(
            pyupgrade_pex,
            argv=(*pyupgrade.args, *request.files),
            input_digest=request.snapshot.digest,
            output_files=request.files,
            description=f"Run pyupgrade on {pluralize(len(request.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return await FixResult.create(request, result)


def rules():
    return [
        *collect_rules(),
        *PyUpgradeRequest.rules(),
        *pex.rules(),
    ]
