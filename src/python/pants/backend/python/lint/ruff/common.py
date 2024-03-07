# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from typing import Optional, Tuple

from typing_extensions import assert_never

from pants.backend.python.lint.ruff.subsystem import Ruff, RuffMode
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.internals.native_engine import Snapshot
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class RunRuffRequest:
    snapshot: Snapshot
    mode: RuffMode
    interpreter_constraints: Optional[InterpreterConstraints] = None


async def run_ruff(
    request: RunRuffRequest,
    ruff: Ruff,
) -> FallibleProcessResult:
    ruff_pex_get = Get(
        VenvPex,
        PexRequest,
        ruff.to_pex_request(interpreter_constraints=request.interpreter_constraints),
    )

    config_files_get = Get(
        ConfigFiles, ConfigFilesRequest, ruff.config_request(request.snapshot.dirs)
    )

    ruff_pex, config_files = await MultiGet(ruff_pex_get, config_files_get)

    input_digest = await Get(
        Digest,
        MergeDigests((request.snapshot.digest, config_files.snapshot.digest)),
    )

    conf_args = [f"--config={ruff.config}"] if ruff.config else []

    extra_initial_args: Tuple[str, ...] = ()
    if request.mode is RuffMode.FORMAT:
        extra_initial_args = ("format",)
    elif request.mode is RuffMode.FIX:
        extra_initial_args = ("check", "--fix")
    elif request.mode is RuffMode.LINT:
        extra_initial_args = ("check",)
    else:
        assert_never(request.mode)

    # `--force-exclude` applies file excludes from config to files provided explicitly
    # The format argument must be passed before force-exclude if Ruff is used for formatting.
    # For other cases, the flags should work the same regardless of the order.
    initial_args = extra_initial_args + ("--force-exclude",)

    result = await Get(
        FallibleProcessResult,
        VenvPexProcess(
            ruff_pex,
            argv=(*initial_args, *conf_args, *ruff.args, *request.snapshot.files),
            input_digest=input_digest,
            output_files=request.snapshot.files,
            description=f"Run ruff {' '.join(initial_args)} on {pluralize(len(request.snapshot.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return result
