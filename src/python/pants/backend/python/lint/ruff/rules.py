# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.lint.ruff.subsystem import Ruff, RuffFieldSet
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.fix import FixResult, FixTargetsRequest
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.fs import Digest, MergeDigests
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


class RuffRequest(FixTargetsRequest):
    field_set_type = RuffFieldSet
    tool_subsystem = Ruff
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


@rule(desc="Fix with ruff", level=LogLevel.DEBUG)
async def ruff_fix(request: RuffRequest.Batch, ruff: Ruff) -> FixResult:
    ruff_pex_get = Get(VenvPex, PexRequest, ruff.to_pex_request())

    config_files_get = Get(
        ConfigFiles, ConfigFilesRequest, ruff.config_request(request.snapshot.dirs)
    )

    ruff_pex, config_files = await MultiGet(ruff_pex_get, config_files_get)

    input_digest = await Get(
        Digest,
        MergeDigests((request.snapshot.digest, config_files.snapshot.digest)),
    )

    conf_args = [f"--config={ruff.config}"] if ruff.config else []

    result = await Get(
        FallibleProcessResult,
        VenvPexProcess(
            ruff_pex,
            argv=("--fix", *conf_args, *ruff.args, *request.files),
            input_digest=input_digest,
            output_directories=request.files,
            description=f"Run ruff on {pluralize(len(request.elements), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return await FixResult.create(request, result, strip_chroot_path=True)


def rules():
    return [*collect_rules(), *RuffRequest.rules(), *pex.rules()]
