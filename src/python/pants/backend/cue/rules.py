# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.backend.cue.subsystem import Cue
from pants.core.util_rules.external_tool import download_external_tool
from pants.engine.fs import MergeDigests, Snapshot
from pants.engine.intrinsics import merge_digests_request_to_digest
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process, fallible_to_exec_result_or_raise
from pants.engine.rules import implicitly
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


def generate_argv(*args: str, files: tuple[str, ...], cue: Cue) -> tuple[str, ...]:
    return args + cue.args + files

async def _run_cue(
    *args: str, cue: Cue, snapshot: Snapshot, platform: Platform, **kwargs
) -> FallibleProcessResult:
    downloaded_cue = await download_external_tool(cue.get_request(platform))
    input_digest = await merge_digests_request_to_digest(MergeDigests((downloaded_cue.digest, snapshot.digest)))
    process_result = await fallible_to_exec_result_or_raise(
        **implicitly(
            Process(
                argv=[downloaded_cue.exe, *generate_argv(*args, files=snapshot.files, cue=cue)],
                input_digest=input_digest,
                description=f"Run `cue {args[0]}` on {pluralize(len(snapshot.files), 'file')}.",
                level=LogLevel.DEBUG,
                **kwargs,
            ),
        )
    )
    # process_result = await Get(
    #     FallibleProcessResult,
        
    # )
    return process_result
