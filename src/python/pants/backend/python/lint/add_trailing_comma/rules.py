# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.lint.add_trailing_comma.skip_field import SkipAddTrailingCommaField
from pants.backend.python.lint.add_trailing_comma.subsystem import AddTrailingComma
from pants.backend.python.target_types import PythonSourceField
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class AddTrailingCommaFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipAddTrailingCommaField).value


class AddTrailingCommaRequest(FmtTargetsRequest):
    field_set_type = AddTrailingCommaFieldSet
    tool_subsystem = AddTrailingComma
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


@rule(desc="Format with add-trailing-comma", level=LogLevel.DEBUG)
async def add_trailing_comma_fmt(
    request: AddTrailingCommaRequest.Batch, add_trailing_comma: AddTrailingComma
) -> FmtResult:
    add_trailing_comma_pex = await Get(VenvPex, PexRequest, add_trailing_comma.to_pex_request())

    result = await Get(
        ProcessResult,
        VenvPexProcess(
            add_trailing_comma_pex,
            argv=(
                "--exit-zero-even-if-changed",
                *add_trailing_comma.args,
                *request.files,
            ),
            input_digest=request.snapshot.digest,
            output_files=request.files,
            description=f"Run add-trailing-comma on {pluralize(len(request.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return await FmtResult.create(request, result)


def rules():
    return [
        *collect_rules(),
        *AddTrailingCommaRequest.rules(),
        *pex.rules(),
    ]
