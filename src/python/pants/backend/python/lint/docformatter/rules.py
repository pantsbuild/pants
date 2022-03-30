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
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest
from pants.engine.internals.native_engine import Snapshot
from pants.engine.internals.selectors import MultiGet
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


@dataclass(frozen=True)
class Setup:
    process: Process
    original_snapshot: Snapshot


def generate_args(
    *, source_files: SourceFiles, docformatter: Docformatter, check_only: bool
) -> Tuple[str, ...]:
    return ("--check" if check_only else "--in-place", *docformatter.args, *source_files.files)


@rule(level=LogLevel.DEBUG)
async def setup_docformatter(request: DocformatterRequest, docformatter: Docformatter) -> Setup:
    docformatter_pex_get = Get(VenvPex, PexRequest, docformatter.to_pex_request())
    source_files_get = Get(
        SourceFiles,
        SourceFilesRequest(field_set.source for field_set in request.field_sets),
    )
    source_files, docformatter_pex = await MultiGet(source_files_get, docformatter_pex_get)

    source_files_snapshot = (
        source_files.snapshot
        if request.prior_formatter_result is None
        else request.prior_formatter_result
    )
    process = await Get(
        Process,
        VenvPexProcess(
            docformatter_pex,
            argv=(
                "--in-place",
                *docformatter.args,
                *source_files_snapshot.files,
            ),
            input_digest=source_files_snapshot.digest,
            output_files=source_files_snapshot.files,
            description=(f"Run Docformatter on {pluralize(len(request.field_sets), 'file')}."),
            level=LogLevel.DEBUG,
        ),
    )
    return Setup(process, original_snapshot=source_files_snapshot)


@rule(desc="Format with docformatter", level=LogLevel.DEBUG)
async def docformatter_fmt(request: DocformatterRequest, docformatter: Docformatter) -> FmtResult:
    if docformatter.skip:
        return FmtResult.skip(formatter_name=request.name)
    setup = await Get(Setup, DocformatterRequest, request)
    result = await Get(ProcessResult, Process, setup.process)
    output_snapshot = await Get(Snapshot, Digest, result.output_digest)
    return FmtResult(
        setup.original_snapshot,
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
