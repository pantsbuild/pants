# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import shlex
import textwrap
from dataclasses import dataclass

from pants.backend.go.subsystems import golang
from pants.backend.go.subsystems.golang import GoRoot
from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.process import BashBinary, Process
from pants.engine.rules import collect_rules, rule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class GoSdkProcess:
    command: tuple[str, ...]
    description: str
    input_digest: Digest = EMPTY_DIGEST
    working_dir: str | None = None
    output_files: tuple[str, ...] = ()
    output_directories: tuple[str, ...] = ()


@rule
async def setup_go_sdk_process(request: GoSdkProcess, goroot: GoRoot, bash: BashBinary) -> Process:
    working_dir_cmd = f"cd '{request.working_dir}'" if request.working_dir else ""

    # Note: The `go` tool requires GOPATH to be an absolute path which can only be resolved
    # from within the execution sandbox. Thus, this code uses a bash script to be able to resolve
    # absolute paths inside the sandbox.
    go_run_script = FileContent(
        "__run_go.sh",
        # TODO: fix this to use `goroot.path` when that is an absolute path. It does not
        #  work currently because of working_dir.
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

    script_digest = await Get(Digest, CreateDigest([go_run_script]))
    input_root_digest = await Get(
        Digest,
        MergeDigests([goroot.digest, script_digest, request.input_digest]),
    )

    return Process(
        argv=[bash.path, go_run_script.path],
        input_digest=input_root_digest,
        description=request.description,
        output_files=request.output_files,
        output_directories=request.output_directories,
        level=LogLevel.DEBUG,
    )


def rules():
    return (*collect_rules(), *golang.rules())
