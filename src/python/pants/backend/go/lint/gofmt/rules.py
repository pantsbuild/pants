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


@rule(level=LogLevel.DEBUG)
async def setup_gofmt(request: GofmtRequest, goroot: GoRoot) -> Process:
    argv = (
        os.path.join(goroot.path, "bin/gofmt"),
        "-w",
        *request.snapshot.files,
    )
    process = Process(
        argv=argv,
        input_digest=request.snapshot.digest,
        output_files=request.snapshot.files,
        description=f"Run gofmt on {pluralize(len(request.snapshot.files), 'file')}.",
        level=LogLevel.DEBUG,
    )
    return process


@rule(desc="Format with gofmt")
async def gofmt_fmt(request: GofmtRequest, gofmt: GofmtSubsystem) -> FmtResult:
    if gofmt.skip:
        return FmtResult.skip(formatter_name=request.name)
    result = await Get(ProcessResult, GofmtRequest, request)
    output_snapshot = await Get(Snapshot, Digest, result.output_digest)
    return FmtResult.create(request, result, output_snapshot)


def rules():
    return [
        *collect_rules(),
        *golang.rules(),
        UnionRule(FmtRequest, GofmtRequest),
    ]
