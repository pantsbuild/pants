# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import Iterable, Mapping

from pants.backend.go.subsystems import golang
from pants.backend.go.subsystems.golang import GolangSubsystem, GoRoot
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import Process
from pants.engine.rules import collect_rules, rule
from pants.python import binaries as python_binaries
from pants.python.binaries import PythonBinary
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
        allow_downloads: bool = False,
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


@dataclass(frozen=True)
class GoSdkRunSetup:
    digest: Digest
    path: str

    CHDIR_ENV = "__PANTS_CHDIR_TO"


@rule
async def go_sdk_invoke_setup(goroot: GoRoot) -> GoSdkRunSetup:
    # Note: The `go` tool requires GOPATH to be an absolute path, which can only be resolved
    # from within the execution sandbox. Thus, this code uses a script to resolve absolute paths.
    script = FileContent(
        "__run_go.py",
        textwrap.dedent(
            f"""\
            import os, sys

            cwd = os.getcwd()
            gopath = os.path.join(cwd, "gopath")
            gocache = os.path.join(cwd, "cache")

            os.environ["GOROOT"] = "{goroot.path}"
            os.environ["GOPATH"] = os.path.join(cwd, "gopath")
            os.environ["GOCACHE"] = os.path.join(cwd, "cache")

            os.makedirs(gopath, exist_ok=True)
            os.makedirs(gocache, exist_ok=True)

            chdir = os.environ["{GoSdkRunSetup.CHDIR_ENV}"]
            if chdir:
                os.chdir(chdir)

            os.execv(os.path.join("{goroot.path}", "bin", "go"), ["go", *sys.argv[1:]])
            """
        ).encode("utf-8"),
    )
    digest = await Get(Digest, CreateDigest([script]))
    return GoSdkRunSetup(digest, script.path)


@rule
async def setup_go_sdk_process(
    request: GoSdkProcess,
    runner: GoSdkRunSetup,
    python: PythonBinary,
    golang_subsystem: GolangSubsystem,
) -> Process:
    input_digest, env_vars = await MultiGet(
        Get(Digest, MergeDigests([runner.digest, request.input_digest])),
        Get(Environment, EnvironmentRequest(golang_subsystem.env_vars_to_pass_to_subprocesses)),
    )
    return Process(
        argv=[python.path, runner.path, *request.command],
        env={
            **env_vars,
            **request.env,
            GoSdkRunSetup.CHDIR_ENV: request.working_dir or "",
        },
        input_digest=input_digest,
        description=request.description,
        output_files=request.output_files,
        output_directories=request.output_directories,
        level=LogLevel.DEBUG,
    )


def rules():
    return (*collect_rules(), *golang.rules(), *python_binaries.rules())
