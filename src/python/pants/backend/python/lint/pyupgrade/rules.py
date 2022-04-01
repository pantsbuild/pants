# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.python.lint.pyupgrade.skip_field import SkipPyUpgradeField
from pants.backend.python.lint.pyupgrade.subsystem import PyUpgrade
from pants.backend.python.target_types import PythonSourceField
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.fmt import FmtRequest, FmtResult
from pants.engine.fs import Digest
from pants.engine.internals.native_engine import Snapshot
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class PyUpgradeFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipPyUpgradeField).value


class PyUpgradeRequest(FmtRequest):
    field_set_type = PyUpgradeFieldSet
    name = PyUpgrade.options_scope


@dataclass(frozen=True)
class PyUpgradeResult:
    process_result: FallibleProcessResult
    original_snapshot: Snapshot


@rule(level=LogLevel.DEBUG)
async def run_pyupgrade(request: PyUpgradeRequest, pyupgrade: PyUpgrade) -> PyUpgradeResult:
    pyupgrade_pex = await Get(VenvPex, PexRequest, pyupgrade.to_pex_request())

    result = await Get(
        FallibleProcessResult,
        VenvPexProcess(
            pyupgrade_pex,
            argv=(*pyupgrade.args, *request.snapshot.files),
            input_digest=request.snapshot.digest,
            output_files=request.snapshot.files,
            description=f"Run pyupgrade on {pluralize(len(request.field_sets), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return PyUpgradeResult(result, original_snapshot=request.snapshot)


@rule(desc="Format with pyupgrade", level=LogLevel.DEBUG)
async def pyupgrade_fmt(result: PyUpgradeResult, pyupgrade: PyUpgrade) -> FmtResult:
    if pyupgrade.skip:
        return FmtResult.skip(formatter_name=PyUpgradeRequest.name)

    output_snapshot = await Get(Snapshot, Digest, result.process_result.output_digest)
    return FmtResult(
        result.original_snapshot,
        output_snapshot,
        stdout=result.process_result.stdout.decode(),
        stderr=result.process_result.stderr.decode(),
        formatter_name=PyUpgradeRequest.name,
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(FmtRequest, PyUpgradeRequest),
        *pex.rules(),
    ]
