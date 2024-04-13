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
from pants.engine.process import FallibleProcessResult, ProcessExecutionFailure
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.option.global_options import KeepSandboxes
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
    request: DocformatterRequest.Batch, docformatter: Docformatter, keep_sandboxes: KeepSandboxes
) -> FmtResult:
    docformatter_pex = await Get(VenvPex, PexRequest, docformatter.to_pex_request())
    description = f"Run Docformatter on {pluralize(len(request.files), 'file')}."
    result = await Get(
        FallibleProcessResult,
        VenvPexProcess(
            docformatter_pex,
            argv=(
                "--in-place",
                *docformatter.args,
                *request.files,
            ),
            input_digest=request.snapshot.digest,
            output_files=request.files,
            description=description,
            level=LogLevel.DEBUG,
        ),
    )
    # Docformatter 1.6.0+ very annoyingly returns an exit code of 3 if run with `--in-place`
    # and any files changed. Earlier versions do not return this code in fmt mode.
    # (All versions return 3 in check mode if any files would have changed, but that is
    # not an issue here).
    if result.exit_code not in [0, 3]:
        # TODO(#12725):It would be more straightforward to force the exception with:
        # result = await Get(ProcessResult, FallibleProcessResult, result)
        raise ProcessExecutionFailure(
            result.exit_code,
            result.stdout,
            result.stderr,
            description,
            keep_sandboxes=keep_sandboxes,
        )

    return await FmtResult.create(request, result)


def rules():
    return [
        *collect_rules(),
        *DocformatterRequest.rules(),
        *pex.rules(),
    ]
