# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import textwrap
from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.go import distribution
from pants.backend.go.distribution import GoLangDistribution
from pants.core.util_rules import external_tool, source_files
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.engine import process
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.internals import build_files
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.process import BashBinary, Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class InvokeGoSdkRequest:
    digest: Digest
    command: Tuple[str, ...]
    description: str
    working_dir: Optional[str] = None
    output_files: Tuple[str, ...] = ()
    output_directories: Tuple[str, ...] = ()


@dataclass(frozen=True)
class InvokeGoSdkResult:
    result: ProcessResult


@rule
async def invoke_go_sdk_command(
    request: InvokeGoSdkRequest,
    goroot: GoLangDistribution,
    bash: BashBinary,
) -> InvokeGoSdkResult:
    downloaded_goroot = await Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        goroot.get_request(Platform.current),
    )

    working_dir_cmd = f"cd '{request.working_dir}'" if request.working_dir else ""

    # Note: The `go` tool requires GOPATH to be an absolute path which can only be resolved from within the
    # execution sandbox. Thus, this code uses a bash script to be able to resolve absolute paths inside the sandbox.
    script_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    "__pants__.sh",
                    textwrap.dedent(
                        f"""\
                export GOROOT="$(/bin/pwd)/go"
                export GOPATH="$(/bin/pwd)/gopath"
                export GOCACHE="$(/bin/pwd)/cache"
                /bin/mkdir -p "$GOPATH" "$GOCACHE"
                {working_dir_cmd}
                exec {' '.join(request.command)}
                """
                    ).encode("utf-8"),
                )
            ]
        ),
    )

    input_root_digest = await Get(
        Digest,
        MergeDigests([downloaded_goroot.digest, script_digest, request.digest]),
    )

    process = Process(
        argv=[bash.path, "__pants__.sh"],
        input_digest=input_root_digest,
        description=request.description,
        output_files=request.output_files,
        output_directories=request.output_directories,
        level=LogLevel.DEBUG,
    )

    result = await Get(ProcessResult, Process, process)

    return InvokeGoSdkResult(result=result)


def rules():
    return collect_rules()
