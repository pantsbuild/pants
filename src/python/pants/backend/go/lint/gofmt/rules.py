# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from dataclasses import dataclass

from pants.backend.go.lint.gofmt.skip_field import SkipGofmtField
from pants.backend.go.lint.gofmt.subsystem import (
    SUPPORTED_GOFMT_ARGS,
    SUPPORTED_GOFMT_ARGS_AS_HELP,
    GofmtSubsystem,
)
from pants.backend.go.target_types import GoPackageSourcesField
from pants.backend.go.util_rules import goroot
from pants.backend.go.util_rules.goroot import GoRoot
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.fs import Digest, MergeDigests
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
    tool_subsystem = GofmtSubsystem
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


class GoFmtUnsupportedArgsPassedError(Exception):
    pass


async def _validate_gofmt_args(args: tuple[str, ...]):
    """Validate that args passed to the gofmt are supported."""
    if not set(args).issubset(SUPPORTED_GOFMT_ARGS):
        raise GoFmtUnsupportedArgsPassedError(
            f"Only the following style related options are supported: {SUPPORTED_GOFMT_ARGS_AS_HELP}."
        )


@rule(desc="Format with gofmt")
async def gofmt_fmt(
    request: GofmtRequest.Batch, gofmt: GofmtSubsystem, goroot: GoRoot
) -> FmtResult:
    await _validate_gofmt_args(gofmt.args)

    argv = (
        os.path.join(goroot.path, "bin/gofmt"),
        "-w",
        *gofmt.args,
        # Filter out non-.go files, e.g. assembly sources, from the file list.
        *(f for f in request.files if f.endswith(".go")),
    )
    result = await Get(
        ProcessResult,
        Process(
            argv=argv,
            input_digest=request.snapshot.digest,
            output_files=request.files,
            description=f"Run gofmt on {pluralize(len(request.files), 'file')}.",
            level=LogLevel.DEBUG,
            immutable_input_digests={".goroot": goroot.digest},
        ),
    )
    return await FmtResult.create(request, result)


def rules():
    return [
        *collect_rules(),
        *goroot.rules(),
        *GofmtRequest.rules(),
    ]
