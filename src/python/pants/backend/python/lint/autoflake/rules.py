# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.lint.autoflake.skip_field import SkipAutoflakeField
from pants.backend.python.lint.autoflake.subsystem import Autoflake
from pants.backend.python.target_types import PythonSourceField
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest
from pants.engine.fs import Digest
from pants.engine.internals.native_engine import Snapshot
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class AutoflakeFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipAutoflakeField).value


class AutoflakeRequest(FmtTargetsRequest):
    field_set_type = AutoflakeFieldSet
    name = Autoflake.options_scope


@rule(desc="Format with Autoflake", level=LogLevel.DEBUG)
async def autoflake_fmt(request: AutoflakeRequest, autoflake: Autoflake) -> FmtResult:
    if autoflake.skip:
        return FmtResult.skip(formatter_name=request.name)
    autoflake_pex = await Get(VenvPex, PexRequest, autoflake.to_pex_request())

    result = await Get(
        ProcessResult,
        VenvPexProcess(
            autoflake_pex,
            argv=(
                "--in-place",
                *autoflake.args,
                *request.snapshot.files,
            ),
            input_digest=request.snapshot.digest,
            output_files=request.snapshot.files,
            description=f"Run Autoflake on {pluralize(len(request.field_sets), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    output_snapshot = await Get(Snapshot, Digest, result.output_digest)
    return FmtResult.create(request, result, output_snapshot, strip_chroot_path=True)


def rules():
    return [
        *collect_rules(),
        UnionRule(FmtTargetsRequest, AutoflakeRequest),
        *pex.rules(),
    ]
