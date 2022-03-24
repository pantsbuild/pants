# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from dataclasses import dataclass

from pants.backend.go.lint.gofmt.skip_field import SkipGofmtField
from pants.backend.go.lint.gofmt.subsystem import GofmtSubsystem
from pants.backend.go.subsystems import golang
from pants.backend.go.subsystems.golang import GoRoot
from pants.backend.go.target_types import GoPackageSourcesField
from pants.core.goals.fmt import FmtRequest, FmtResult
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest
from pants.engine.internals.native_engine import Snapshot
from pants.engine.internals.selectors import Get
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class GofmtFieldSet(FieldSet):
    required_fields = (GoPackageSourcesField,)

    sources: GoPackageSourcesField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipGofmtField).value


class GofmtRequest(FmtRequest):
    field_set_type = GofmtFieldSet
    name = GofmtSubsystem.options_scope


@dataclass(frozen=True)
class Setup:
    process: Process
    original_snapshot: Snapshot


@rule(level=LogLevel.DEBUG)
async def setup_gofmt(request: GofmtRequest, goroot: GoRoot) -> Setup:
    source_files = await Get(
        SourceFiles,
        SourceFilesRequest(field_set.sources for field_set in request.field_sets),
    )
    source_files_snapshot = (
        source_files.snapshot
        if request.prior_formatter_result is None
        else request.prior_formatter_result
    )

    argv = (
        os.path.join(goroot.path, "bin/gofmt"),
        "-w",
        *source_files_snapshot.files,
    )
    process = Process(
        argv=argv,
        input_digest=source_files_snapshot.digest,
        output_files=source_files_snapshot.files,
        description=f"Run gofmt on {pluralize(len(source_files_snapshot.files), 'file')}.",
        level=LogLevel.DEBUG,
    )
    return Setup(process=process, original_snapshot=source_files_snapshot)


@rule(desc="Format with gofmt")
async def gofmt_fmt(request: GofmtRequest, gofmt: GofmtSubsystem) -> FmtResult:
    if gofmt.skip:
        return FmtResult.skip(formatter_name=request.name)
    setup = await Get(Setup, GofmtRequest, request)
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
        *golang.rules(),
        UnionRule(FmtRequest, GofmtRequest),
    ]
