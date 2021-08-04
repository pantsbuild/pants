# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import shlex
import textwrap
from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.go.distribution import GoLangDistribution
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.process import BashBinary, Process
from pants.engine.rules import collect_rules, rule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class GoSdkProcess:
    input_digest: Digest
    command: Tuple[str, ...]
    description: str
    working_dir: Optional[str] = None
    output_files: Tuple[str, ...] = ()
    output_directories: Tuple[str, ...] = ()


@rule
async def setup_go_sdk_command(
    request: GoSdkProcess,
    goroot: GoLangDistribution,
    bash: BashBinary,
) -> Process:
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
                exec "${{GOROOT}}/bin/go" {' '.join(shlex.quote(arg) for arg in request.command)}
                """
                    ).encode("utf-8"),
                )
            ]
        ),
    )

    input_root_digest = await Get(
        Digest,
        MergeDigests([downloaded_goroot.digest, script_digest, request.input_digest]),
    )

    return Process(
        argv=[bash.path, "__pants__.sh"],
        input_digest=input_root_digest,
        description=request.description,
        output_files=request.output_files,
        output_directories=request.output_directories,
        level=LogLevel.DEBUG,
    )


def rules():
    return collect_rules()
