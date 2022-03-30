# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.lint.yapf.skip_field import SkipYapfField
from pants.backend.python.lint.yapf.subsystem import Yapf
from pants.backend.python.target_types import PythonSourceField
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.fmt import FmtRequest, FmtResult
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.internals.native_engine import Snapshot
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class YapfFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipYapfField).value


class YapfRequest(FmtRequest):
    field_set_type = YapfFieldSet
    name = Yapf.options_scope


@dataclass(frozen=True)
class Setup:
    process: Process
    original_snapshot: Snapshot


@rule(level=LogLevel.DEBUG)
async def setup_yapf(request: YapfRequest, yapf: Yapf) -> Setup:
    yapf_pex_get = Get(VenvPex, PexRequest, yapf.to_pex_request())
    source_files_get = Get(
        SourceFiles,
        SourceFilesRequest(field_set.source for field_set in request.field_sets),
    )
    source_files, yapf_pex = await MultiGet(source_files_get, yapf_pex_get)

    source_files_snapshot = (
        source_files.snapshot
        if request.prior_formatter_result is None
        else request.prior_formatter_result
    )

    config_files = await Get(
        ConfigFiles, ConfigFilesRequest, yapf.config_request(source_files_snapshot.dirs)
    )
    input_digest = await Get(
        Digest, MergeDigests((source_files_snapshot.digest, config_files.snapshot.digest))
    )

    process = await Get(
        Process,
        VenvPexProcess(
            yapf_pex,
            argv=(
                *yapf.args,
                "--in-place",
                *(("--style", yapf.config) if yapf.config else ()),
                *source_files_snapshot.files,
            ),
            input_digest=input_digest,
            output_files=source_files_snapshot.files,
            description=f"Run yapf on {pluralize(len(request.field_sets), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return Setup(process, original_snapshot=source_files_snapshot)


@rule(desc="Format with yapf", level=LogLevel.DEBUG)
async def yapf_fmt(request: YapfRequest, yapf: Yapf) -> FmtResult:
    if yapf.skip:
        return FmtResult.skip(formatter_name=request.name)
    setup = await Get(Setup, YapfRequest, request)
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
        UnionRule(FmtRequest, YapfRequest),
        *pex.rules(),
    ]
