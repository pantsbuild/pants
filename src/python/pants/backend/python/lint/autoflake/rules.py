# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.lint.autoflake.skip_field import SkipAutoflakeField
from pants.backend.python.lint.autoflake.subsystem import Autoflake
from pants.backend.python.target_types import InterpreterConstraintsField, PythonSourceField
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
from pants.util.strutil import pluralize, strip_v2_chroot_path


@dataclass(frozen=True)
class AutoflakeFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField
    interpreter_constraints: InterpreterConstraintsField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipAutoflakeField).value


class AutoflakeRequest(FmtRequest):
    field_set_type = AutoflakeFieldSet
    name = Autoflake.options_scope


@dataclass(frozen=True)
class Setup:
    process: Process
    original_snapshot: Snapshot


@rule(level=LogLevel.DEBUG)
async def setup_autoflake(request: AutoflakeRequest, autoflake: Autoflake) -> Setup:
    autoflake_pex_get = Get(VenvPex, PexRequest, autoflake.to_pex_request())

    source_files_get = Get(
        SourceFiles,
        SourceFilesRequest(field_set.source for field_set in request.field_sets),
    )

    source_files, autoflake_pex = await MultiGet(source_files_get, autoflake_pex_get)
    source_files_snapshot = (
        source_files.snapshot
        if request.prior_formatter_result is None
        else request.prior_formatter_result
    )

    process = await Get(
        Process,
        VenvPexProcess(
            autoflake_pex,
            argv=(
                "--in-place",
                "--remove-all-unused-imports",
                *autoflake.args,
                *source_files_snapshot.files,
            ),
            input_digest=source_files_snapshot.digest,
            output_files=source_files_snapshot.files,
            description=f"Run Autoflake on {pluralize(len(request.field_sets), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return Setup(process, original_snapshot=source_files_snapshot)


@rule(desc="Format with Autoflake", level=LogLevel.DEBUG)
async def autoflake_fmt(request: AutoflakeRequest, autoflake: Autoflake) -> FmtResult:
    if autoflake.skip:
        return FmtResult.skip(formatter_name=request.name)
    setup = await Get(Setup, AutoflakeRequest, request)
    result = await Get(ProcessResult, Process, setup.process)
    output_snapshot = await Get(Snapshot, Digest, result.output_digest)
    return FmtResult(
        setup.original_snapshot,
        output_snapshot,
        stdout=strip_v2_chroot_path(result.stdout),
        stderr=strip_v2_chroot_path(result.stderr),
        formatter_name=request.name,
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(FmtRequest, AutoflakeRequest),
        *pex.rules(),
    ]
