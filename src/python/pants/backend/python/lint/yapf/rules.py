# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.python.lint.yapf.skip_field import SkipYapfField
from pants.backend.python.lint.yapf.subsystem import Yapf
from pants.backend.python.target_types import PythonSourceField
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.fmt import FmtRequest, FmtResult, FmtTargetsRequest
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.fs import Digest, MergeDigests
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule, rule_helper
from pants.engine.target import FieldSet, Target
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class YapfFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipYapfField).value


class YapfRequest(FmtTargetsRequest):
    field_set_type = YapfFieldSet
    tool_subsystem = Yapf
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


@rule_helper
async def _run_yapf(
    request: FmtRequest.Batch,
    yapf: Yapf,
    interpreter_constraints: InterpreterConstraints | None = None,
) -> FmtResult:
    yapf_pex_get = Get(
        VenvPex, PexRequest, yapf.to_pex_request(interpreter_constraints=interpreter_constraints)
    )
    config_files_get = Get(
        ConfigFiles, ConfigFilesRequest, yapf.config_request(request.snapshot.dirs)
    )
    yapf_pex, config_files = await MultiGet(yapf_pex_get, config_files_get)

    input_digest = await Get(
        Digest, MergeDigests((request.snapshot.digest, config_files.snapshot.digest))
    )

    result = await Get(
        ProcessResult,
        VenvPexProcess(
            yapf_pex,
            argv=(
                *yapf.args,
                "--in-place",
                *(("--style", yapf.config) if yapf.config else ()),
                *request.files,
            ),
            input_digest=input_digest,
            output_files=request.files,
            description=f"Run yapf on {pluralize(len(request.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return await FmtResult.create(request, result)


@rule(desc="Format with yapf", level=LogLevel.DEBUG)
async def yapf_fmt(request: YapfRequest.Batch, yapf: Yapf) -> FmtResult:
    return await _run_yapf(request, yapf)


def rules():
    return [
        *collect_rules(),
        *YapfRequest.rules(),
        *pex.rules(),
    ]
