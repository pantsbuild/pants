# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.rust.lint.rustfmt import skip_field
from pants.backend.rust.lint.rustfmt.skip_field import SkipRustfmtField
from pants.backend.rust.lint.rustfmt.subsystem import RustfmtSubsystem
from pants.backend.rust.target_types import RustCrateSourcesField
from pants.backend.rust.util_rules.toolchains import RustToolchainProcess
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
class RustfmtFieldSet(FieldSet):
    required_fields = (RustCrateSourcesField,)

    sources: RustCrateSourcesField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipRustfmtField).value


class RustfmtRequest(FmtRequest):
    field_set_type = RustfmtFieldSet
    name = RustfmtSubsystem.options_scope


@rule(level=LogLevel.DEBUG)
async def setup_rustfmt(request: RustfmtRequest) -> Process:
    files = [f for f in request.snapshot.files if f.endswith(".rs")]  # filter out Cargo.toml
    process = await Get(
        Process,
        RustToolchainProcess(
            binary="rustfmt",
            args=files,
            input_digest=request.snapshot.digest,
            output_files=request.snapshot.files,
            description=f"Run rustfmt on {pluralize(len(files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return process


@rule(desc="Format with rustfmt")
async def rustfmt_fmt(request: RustfmtRequest, rustfmt: RustfmtSubsystem) -> FmtResult:
    if rustfmt.skip:
        return FmtResult.skip(formatter_name=request.name)
    result = await Get(ProcessResult, RustfmtRequest, request)
    output_snapshot = await Get(Snapshot, Digest, result.output_digest)
    return FmtResult.create(request, result, output_snapshot)


def rules():
    return [
        *collect_rules(),
        *skip_field.rules(),
        UnionRule(FmtRequest, RustfmtRequest),
    ]