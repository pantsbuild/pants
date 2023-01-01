# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.lint.docformatter.skip_field import SkipDocformatterField
from pants.backend.python.lint.docformatter.subsystem import Docformatter
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
class DocformatterFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipDocformatterField).value


class DocformatterRequest(FmtTargetsRequest):
    field_set_type = DocformatterFieldSet
    tool_subsystem = Docformatter
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


@rule(desc="Format with docformatter", level=LogLevel.DEBUG)
async def docformatter_fmt(
    request: DocformatterRequest.Batch, docformatter: Docformatter
) -> FmtResult:
    docformatter_pex = await Get(VenvPex, PexRequest, docformatter.to_pex_request())
    result = await Get(
        ProcessResult,
        VenvPexProcess(
            docformatter_pex,
            argv=(
                "--in-place",
                *docformatter.args,
                *request.files,
            ),
            input_digest=request.snapshot.digest,
            output_files=request.files,
            description=(f"Run Docformatter on {pluralize(len(request.files), 'file')}."),
            level=LogLevel.DEBUG,
        ),
    )
    return await FmtResult.create(request, result)


def rules():
    return [
        *collect_rules(),
        *DocformatterRequest.rules(),
        *pex.rules(),
    ]
