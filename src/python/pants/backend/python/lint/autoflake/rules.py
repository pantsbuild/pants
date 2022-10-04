# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.lint.autoflake.skip_field import SkipAutoflakeField
from pants.backend.python.lint.autoflake.subsystem import Autoflake
from pants.backend.python.target_types import PythonSourceField
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest, Partitions
from pants.engine.fs import Digest
from pants.engine.internals.native_engine import Snapshot
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class AutoflakeFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipAutoflakeField).value


class AutoflakeRequest(FmtTargetsRequest):
    field_set_type = AutoflakeFieldSet
    name = Autoflake.options_scope


@rule
async def partition(request: AutoflakeRequest.PartitionRequest, autoflake: Autoflake) -> Partitions:
    return (
        Partitions()
        if autoflake.skip
        else Partitions.single_partition(
            field_set.source.file_path for field_set in request.field_sets
        )
    )


@rule(desc="Format with Autoflake", level=LogLevel.DEBUG)
async def autoflake_fmt(request: AutoflakeRequest.SubPartition, autoflake: Autoflake) -> FmtResult:
    autoflake_pex = await Get(VenvPex, PexRequest, autoflake.to_pex_request())

    result = await Get(
        ProcessResult,
        VenvPexProcess(
            autoflake_pex,
            argv=(
                "--in-place",
                *autoflake.args,
                *request.files,
            ),
            input_digest=request.snapshot.digest,
            output_files=request.files,
            description=f"Run Autoflake on {pluralize(len(request.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    output_snapshot = await Get(Snapshot, Digest, result.output_digest)
    return FmtResult.create(
        result,
        request.snapshot,
        output_snapshot,
        strip_chroot_path=True,
        formatter_name=AutoflakeRequest.name,
    )


def rules():
    return [
        *collect_rules(),
        *AutoflakeRequest.registration_rules(),
        *pex.rules(),
    ]
