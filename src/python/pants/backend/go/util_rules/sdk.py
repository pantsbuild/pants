# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import shlex
import textwrap
from dataclasses import dataclass
from typing import Iterable, Mapping

from pants.backend.go.subsystems import golang
from pants.backend.go.subsystems.golang import GoRoot
from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.process import BashBinary, Process
from pants.engine.rules import collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init


@frozen_after_init
@dataclass(unsafe_hash=True)
class GoSdkProcess:
    command: tuple[str, ...]
    description: str
    env: FrozenDict[str, str]
    input_digest: Digest = EMPTY_DIGEST
    working_dir: str | None = None
    output_files: tuple[str, ...] = ()
    output_directories: tuple[str, ...] = ()

    def __init__(
        self,
        command: Iterable[str],
        *,
        description: str,
        env: Mapping[str, str] | None = None,
        input_digest: Digest = EMPTY_DIGEST,
        working_dir: str | None = None,
        output_files: Iterable[str] = (),
        output_directories: Iterable[str] = (),
    ) -> None:
        self.command = tuple(command)
        self.description = description
        self.env = FrozenDict(env or {})
        self.input_digest = input_digest
        self.working_dir = working_dir
        self.output_files = tuple(output_files)
        self.output_directories = tuple(output_directories)


@rule
async def setup_go_sdk_process(request: GoSdkProcess, goroot: GoRoot, bash: BashBinary) -> Process:
    working_dir_cmd = f"cd '{request.working_dir}'" if request.working_dir else ""

    # Note: The `go` tool requires GOPATH to be an absolute path which can only be resolved
    # from within the execution sandbox. Thus, this code uses a bash script to be able to resolve
    # absolute paths inside the sandbox.
    go_run_script = FileContent(
        "__run_go.sh",
        textwrap.dedent(
            f"""\
            export GOROOT={goroot.path}
            export GOPATH="$(/bin/pwd)/gopath"
            export GOCACHE="$(/bin/pwd)/cache"
            /bin/mkdir -p "$GOPATH" "$GOCACHE"
            {working_dir_cmd}
            exec "{goroot.path}/bin/go" {' '.join(shlex.quote(arg) for arg in request.command)}
            """
        ).encode("utf-8"),
    )

    script_digest = await Get(Digest, CreateDigest([go_run_script]))
    input_digest = await Get(Digest, MergeDigests([script_digest, request.input_digest]))
    return Process(
        argv=[bash.path, go_run_script.path],
        input_digest=input_digest,
        description=request.description,
        output_files=request.output_files,
        output_directories=request.output_directories,
        level=LogLevel.DEBUG,
    )


def rules():
    return (*collect_rules(), *golang.rules())
