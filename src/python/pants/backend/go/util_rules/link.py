# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.go.util_rules.build_opts import GoBuildOptions
from pants.backend.go.util_rules.sdk import GoSdkProcess, GoSdkToolIDRequest, GoSdkToolIDResult
from pants.engine.fs import Digest
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, collect_rules, rule


@dataclass(frozen=True)
class LinkGoBinaryRequest:
    """Link a Go binary from package archives and an import configuration."""

    input_digest: Digest
    archives: tuple[str, ...]
    build_opts: GoBuildOptions
    import_config_path: str
    output_filename: str
    description: str


@dataclass(frozen=True)
class LinkedGoBinary:
    """A linked Go binary stored in a `Digest`."""

    digest: Digest


@rule
async def link_go_binary(request: LinkGoBinaryRequest) -> LinkedGoBinary:
    link_tool_id = await Get(GoSdkToolIDResult, GoSdkToolIDRequest("link"))
    maybe_race_arg = ["-race"] if request.build_opts.with_race_detector else []
    maybe_msan_arg = ["-msan"] if request.build_opts.with_msan else []
    maybe_asan_arg = ["-asan"] if request.build_opts.with_asan else []
    result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=request.input_digest,
            command=(
                "tool",
                "link",
                *maybe_race_arg,
                *maybe_msan_arg,
                *maybe_asan_arg,
                "-importcfg",
                request.import_config_path,
                "-o",
                request.output_filename,
                "-buildmode=exe",  # seen in `go build -x` output
                *request.archives,
            ),
            env={
                "__PANTS_GO_LINK_TOOL_ID": link_tool_id.tool_id,
            },
            description=f"Link Go binary: {request.output_filename}",
            output_files=(request.output_filename,),
        ),
    )

    return LinkedGoBinary(result.output_digest)


def rules():
    return collect_rules()
