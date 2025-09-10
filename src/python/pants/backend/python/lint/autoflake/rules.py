# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import cast

from pants.backend.python.lint.autoflake.skip_field import SkipAutoflakeField
from pants.backend.python.lint.autoflake.subsystem import Autoflake
from pants.backend.python.target_types import PythonSourceField
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import VenvPexProcess, create_venv_pex
from pants.core.goals.fix import FixResult, FixTargetsRequest
from pants.core.goals.multi_tool_goal_helper import SkippableSubsystem
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.process import execute_process_or_raise
from pants.engine.rules import collect_rules, implicitly, rule
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
    tool_subsystem = cast(type[SkippableSubsystem], Autoflake)
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


@rule(desc="Fix with Autoflake", level=LogLevel.DEBUG)
async def autoflake_fix(request: AutoflakeRequest.Batch, autoflake: Autoflake) -> FixResult:
    autoflake_pex = await create_venv_pex(**implicitly(autoflake.to_pex_request()))
    result = await execute_process_or_raise(
        **implicitly(
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
            )
        )
    )
    return await FixResult.create(request, result)


def rules():
    return (
        *collect_rules(),
        *AutoflakeRequest.rules(),
        *pex.rules(),
    )
