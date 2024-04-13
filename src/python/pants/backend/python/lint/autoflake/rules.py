# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.lint.autoflake.skip_field import SkipAutoflakeField
from pants.backend.python.lint.autoflake.subsystem import Autoflake
from pants.backend.python.target_types import PythonSourceField
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.fix import FixResult, FixTargetsRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class AutoflakeFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipAutoflakeField).value


class AutoflakeRequest(FixTargetsRequest):
    field_set_type = AutoflakeFieldSet
    tool_subsystem = Autoflake
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


@rule(desc="Fix with Autoflake", level=LogLevel.DEBUG)
async def autoflake_fix(request: AutoflakeRequest.Batch, autoflake: Autoflake) -> FixResult:
    autoflake_pex = await Get(VenvPex, PexRequest, autoflake.to_pex_request())

    result = await Get(
        ProcessResult,
        VenvPexProcess(
            autoflake_pex,
            argv=(
                "--in-place",
                *autoflake.args,
                *request.files,
            ),
            input_digest=request.snapshot.digest,
            output_files=request.files,
            description=f"Run Autoflake on {pluralize(len(request.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return await FixResult.create(request, result)


def rules():
    return [
        *collect_rules(),
        *AutoflakeRequest.rules(),
        *pex.rules(),
    ]
