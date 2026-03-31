# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
from dataclasses import dataclass
from typing import assert_never

from pants.backend.python.lint.ruff.subsystem import Ruff, RuffMode
from pants.core.goals.lint import REPORT_DIR
from pants.core.util_rules.config_files import find_config_file
from pants.core.util_rules.external_tool import download_external_tool
from pants.engine.fs import CreateDigest, Directory, MergeDigests
from pants.engine.internals.native_engine import Snapshot
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import create_digest, execute_process, merge_digests
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import implicitly
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class RunRuffRequest:
    snapshot: Snapshot
    mode: RuffMode


async def run_ruff(
    request: RunRuffRequest,
    ruff: Ruff,
    platform: Platform,
) -> FallibleProcessResult:
    ruff_tool_get = download_external_tool(ruff.get_request(platform))
    config_files_get = find_config_file(ruff.config_request(request.snapshot.dirs))
    # Ensure that the empty report dir exists.
    report_directory_digest_get = create_digest(CreateDigest([Directory(REPORT_DIR)]))

    ruff_tool, config_files, report_directory = await concurrently(
        ruff_tool_get, config_files_get, report_directory_digest_get
    )

    input_digest = await merge_digests(
        MergeDigests(
            (
                request.snapshot.digest,
                config_files.snapshot.digest,
                report_directory,
            )
        ),
    )

    conf_args = [f"--config={ruff.config}"] if ruff.config else []

    extra_initial_args: tuple[str, ...] = ()
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

    immutable_input_key = "__ruff_tool"
    exe_path = os.path.join(immutable_input_key, ruff_tool.exe)

    result = await execute_process(
        Process(
            argv=(exe_path, *initial_args, *conf_args, *ruff.args, *request.snapshot.files),
            input_digest=input_digest,
            immutable_input_digests={immutable_input_key: ruff_tool.digest},
            output_files=request.snapshot.files,
            output_directories=(REPORT_DIR,) if request.mode is RuffMode.LINT else (),
            description=f"Run ruff {' '.join(initial_args)} on {pluralize(len(request.snapshot.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
        **implicitly(),
    )
    return result
