# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from dataclasses import dataclass

from pants.backend.go.lint.gofmt.skip_field import SkipGofmtField
from pants.backend.go.lint.gofmt.subsystem import GofmtSubsystem
from pants.backend.go.target_types import GoPackageSourcesField
from pants.backend.go.util_rules import goroot
from pants.backend.go.util_rules.goroot import GoRoot
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest, Partitions
from pants.engine.fs import Digest
from pants.engine.internals.native_engine import Snapshot
from pants.engine.internals.selectors import Get
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class GofmtFieldSet(FieldSet):
    required_fields = (GoPackageSourcesField,)

    sources: GoPackageSourcesField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipGofmtField).value


class GofmtRequest(FmtTargetsRequest):
    field_set_type = GofmtFieldSet
    name = GofmtSubsystem.options_scope


@rule
async def partition_gofmt(
    request: GofmtRequest.PartitionRequest, gofmt: GofmtSubsystem
) -> Partitions:
    return (
        Partitions()
        if gofmt.skip
        else Partitions.single_partition(
            field_set.sources.file_path for field_set in request.field_sets
        )
    )


@rule(desc="Format with gofmt")
async def gofmt_fmt(request: GofmtRequest.SubPartition, goroot: GoRoot) -> FmtResult:
    argv = (
        os.path.join(goroot.path, "bin/gofmt"),
        "-w",
        *request.files,
    )
    result = await Get(
        ProcessResult,
        Process(
            argv=argv,
            input_digest=request.snapshot.digest,
            output_files=request.files,
            description=f"Run gofmt on {pluralize(len(request.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    output_snapshot = await Get(Snapshot, Digest, result.output_digest)
    return FmtResult.create(
        result, request.snapshot, output_snapshot, formatter_name=GofmtRequest.name
    )


def rules():
    return [
        *collect_rules(),
        *goroot.rules(),
        *GofmtRequest.registration_rules(),
    ]
