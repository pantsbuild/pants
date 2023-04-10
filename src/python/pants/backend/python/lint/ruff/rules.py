# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.python.lint.ruff.subsystem import Ruff, RuffFieldSet
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.fix import FixResult, FixTargetsRequest
from pants.core.goals.lint import LintRequest, LintTargetsRequest
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.fs import Digest, MergeDigests
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


class RuffFixRequest(FixTargetsRequest):
    field_set_type = RuffFieldSet
    tool_subsystem = Ruff
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


class RuffLintRequest(LintTargetsRequest):
    field_set_type = RuffFieldSet
    tool_subsystem = Ruff
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


@dataclass(frzoen=True)
class _RunRuffRequest:
    batch: LintRequest.Batch
    is_fix: bool


@rule(level=LogLevel.DEBUG)
async def run_ruff(
    request: _RunRuffRequest,
    ruff: Ruff,
) -> FallibleProcessResult:
    ruff_pex_get = Get(VenvPex, PexRequest, ruff.to_pex_request())

    config_files_get = Get(
        ConfigFiles, ConfigFilesRequest, ruff.config_request(request.batch.snapshot.dirs)
    )

    ruff_pex, config_files = await MultiGet(ruff_pex_get, config_files_get)

    input_digest = await Get(
        Digest,
        MergeDigests((request.batch.snapshot.digest, config_files.snapshot.digest)),
    )

    conf_args = [f"--config={ruff.config}"] if ruff.config else []
    maybe_fix_args = ("--fix",) if request.is_fix else ()

    result = await Get(
        FallibleProcessResult,
        VenvPexProcess(
            ruff_pex,
            argv=(*maybe_fix_args, *conf_args, *ruff.args, *request.batch.files),
            input_digest=input_digest,
            output_files=request.batch.files,
            description=f"Run ruff {' '.join(maybe_fix_args)} on {pluralize(len(request.batch.elements), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return result


@rule(desc="Fix with ruff", level=LogLevel.DEBUG)
async def ruff_fix(request: RuffFixRequest.Batch, ruff: Ruff) -> FixResult:
    result = await Get(FallibleProcessResult, _RunRuffRequest(batch=request, is_fix=True))
    return await FixResult.create(request, result, strip_chroot_path=True)


@rule(desc="Lint with ruff", level=LogLevel.DEBUG)
async def ruff_lint(request: RuffFixRequest.Batch) -> FixResult:
    result = await Get(FallibleProcessResult, _RunRuffRequest(batch=request, is_fix=False))
    return await FixResult.create(request, result, strip_chroot_path=True)


def rules():
    return [
        *collect_rules(),
        *RuffFixRequest.rules(),
        *pex.rules(),
    ]
