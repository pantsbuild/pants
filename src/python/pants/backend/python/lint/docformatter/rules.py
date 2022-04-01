# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Tuple

from pants.backend.python.lint.docformatter.skip_field import SkipDocformatterField
from pants.backend.python.lint.docformatter.subsystem import Docformatter
from pants.backend.python.target_types import PythonSourceField
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.fmt import FmtRequest, FmtResult
from pants.core.util_rules.source_files import SourceFiles
from pants.engine.fs import Digest
from pants.engine.internals.native_engine import Snapshot
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class DocformatterFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipDocformatterField).value


class DocformatterRequest(FmtRequest):
    field_set_type = DocformatterFieldSet
    name = Docformatter.options_scope


@rule(level=LogLevel.DEBUG)
async def setup_docformatter(request: DocformatterRequest, docformatter: Docformatter) -> Process:
    docformatter_pex = await Get(VenvPex, PexRequest, docformatter.to_pex_request())

    process = await Get(
        Process,
        VenvPexProcess(
            docformatter_pex,
            argv=(
                "--in-place",
                *docformatter.args,
                *request.snapshot.files,
            ),
            input_digest=request.snapshot.digest,
            output_files=request.snapshot.files,
            description=(f"Run Docformatter on {pluralize(len(request.field_sets), 'file')}."),
            level=LogLevel.DEBUG,
        ),
    )
    return process


@rule(desc="Format with docformatter", level=LogLevel.DEBUG)
async def docformatter_fmt(request: DocformatterRequest, docformatter: Docformatter) -> FmtResult:
    if docformatter.skip:
        return FmtResult.skip(formatter_name=request.name)
    process = await Get(Process, DocformatterRequest, request)
    result = await Get(ProcessResult, Process, process)
    output_snapshot = await Get(Snapshot, Digest, result.output_digest)
    return FmtResult(
        request.snapshot,
        output_snapshot,
        stdout=result.stdout.decode(),
        stderr=result.stderr.decode(),
        formatter_name=request.name,
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(FmtRequest, DocformatterRequest),
        *pex.rules(),
    ]
