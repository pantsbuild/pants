# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import Iterable, Mapping

from pants.backend.go.subsystems.golang import GolangSubsystem
from pants.backend.go.util_rules import goroot
from pants.backend.go.util_rules.goroot import GoRoot
from pants.core.util_rules.system_binaries import BashBinary
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult
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
    input_digest: Digest
    working_dir: str | None
    output_files: tuple[str, ...]
    output_directories: tuple[str, ...]
    platform: Platform | None

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
        allow_downloads: bool = False,
        platform: Platform | None = None,
    ) -> None:
        self.command = tuple(command)
        self.description = description
        self.env = (
            FrozenDict(env or {})
            if allow_downloads
            else FrozenDict({**(env or {}), "GOPROXY": "off"})
        )
        self.input_digest = input_digest
        self.working_dir = working_dir
        self.output_files = tuple(output_files)
        self.output_directories = tuple(output_directories)
        self.platform = platform


@dataclass(frozen=True)
class GoSdkRunSetup:
    digest: Digest
    script: FileContent

    CHDIR_ENV = "__PANTS_CHDIR_TO"


@rule
async def go_sdk_invoke_setup(goroot: GoRoot) -> GoSdkRunSetup:
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
            if [ -n "${GoSdkRunSetup.CHDIR_ENV}" ]; then
              cd "${GoSdkRunSetup.CHDIR_ENV}"
            fi
            exec "{goroot.path}/bin/go" "$@"
            """
        ).encode("utf-8"),
    )

    digest = await Get(Digest, CreateDigest([go_run_script]))
    return GoSdkRunSetup(digest, go_run_script)


@rule
async def setup_go_sdk_process(
    request: GoSdkProcess,
    go_sdk_run: GoSdkRunSetup,
    bash: BashBinary,
    golang_subsystem: GolangSubsystem,
    goroot: GoRoot,
) -> Process:
    input_digest, env_vars = await MultiGet(
        Get(Digest, MergeDigests([go_sdk_run.digest, request.input_digest])),
        Get(Environment, EnvironmentRequest(golang_subsystem.env_vars_to_pass_to_subprocesses)),
    )
    return Process(
        argv=[bash.path, go_sdk_run.script.path, *request.command],
        env={
            **env_vars,
            **request.env,
            GoSdkRunSetup.CHDIR_ENV: request.working_dir or "",
            # TODO: Maybe could just use MAJOR.MINOR for version part here?
            "__PANTS_GO_SDK_CACHE_KEY": f"{goroot.version}/{goroot.goos}/{goroot.goarch}",
        },
        input_digest=input_digest,
        description=request.description,
        output_files=request.output_files,
        output_directories=request.output_directories,
        level=LogLevel.DEBUG,
        platform=request.platform,
    )


@dataclass(frozen=True)
class GoSdkToolIDRequest:
    tool_name: str


@dataclass(frozen=True)
class GoSdkToolIDResult:
    tool_name: str
    tool_id: str


@rule
async def compute_go_tool_id(request: GoSdkToolIDRequest) -> GoSdkToolIDResult:
    result = await Get(
        ProcessResult,
        GoSdkProcess(
            ["tool", request.tool_name, "-V=full"],
            description=f"Obtain tool ID for Go tool `{request.tool_name}`.",
        ),
    )
    return GoSdkToolIDResult(tool_name=request.tool_name, tool_id=result.stdout.decode().strip())


def rules():
    return (*collect_rules(), *goroot.rules())
