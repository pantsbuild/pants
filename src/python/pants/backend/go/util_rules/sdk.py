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
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class GoSdkProcess:
    command: tuple[str, ...]
    description: str
    env: FrozenDict[str, str]
    input_digest: Digest
    working_dir: str | None
    output_files: tuple[str, ...]
    output_directories: tuple[str, ...]
    replace_sandbox_root_in_args: bool

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
        replace_sandbox_root_in_args: bool = False,
    ) -> None:
        object.__setattr__(self, "command", tuple(command))
        object.__setattr__(self, "description", description)
        object.__setattr__(
            self,
            "env",
            (
                FrozenDict(env or {})
                if allow_downloads
                else FrozenDict({**(env or {}), "GOPROXY": "off"})
            ),
        )
        object.__setattr__(self, "input_digest", input_digest)
        object.__setattr__(self, "working_dir", working_dir)
        object.__setattr__(self, "output_files", tuple(output_files))
        object.__setattr__(self, "output_directories", tuple(output_directories))
        object.__setattr__(self, "replace_sandbox_root_in_args", replace_sandbox_root_in_args)


@dataclass(frozen=True)
class GoSdkRunSetup:
    digest: Digest
    script: FileContent

    CHDIR_ENV = "__PANTS_CHDIR_TO"
    SANDBOX_ROOT_ENV = "__PANTS_REPLACE_SANDBOX_ROOT"


@rule
async def go_sdk_invoke_setup(goroot: GoRoot) -> GoSdkRunSetup:
    # Note: The `go` tool requires GOPATH to be an absolute path which can only be resolved
    # from within the execution sandbox. Thus, this code uses a bash script to be able to resolve
    # absolute paths inside the sandbox.

    script = textwrap.dedent(
        f"""\
            export sandbox_root="$(/bin/pwd)"
            export GOPATH="${{sandbox_root}}/gopath"
            export GOCACHE="${{sandbox_root}}/cache"
            export GOROOT="${{sandbox_root}}/{goroot.path}"
            /bin/mkdir -p "$GOPATH" "$GOCACHE"
            if [ -n "${GoSdkRunSetup.CHDIR_ENV}" ]; then
              cd "${GoSdkRunSetup.CHDIR_ENV}"
            fi
            if [ -n "${GoSdkRunSetup.SANDBOX_ROOT_ENV}" ]; then
              export __PANTS_SANDBOX_ROOT__="$sandbox_root"
              args=("${{@//__PANTS_SANDBOX_ROOT__/$sandbox_root}}")
              set -- "${{args[@]}}"
            fi

            exec "${{GOROOT}}/bin/go" "$@"
            """
    )

    go_run_script = FileContent(
        "__run_go.sh",
        script.encode("utf-8"),
    )

    digest = await Get(Digest, CreateDigest([go_run_script]))
    return GoSdkRunSetup(digest, go_run_script)


@rule
async def setup_go_sdk_process(
    request: GoSdkProcess,
    go_sdk_run: GoSdkRunSetup,
    bash: BashBinary,
    golang_env_aware: GolangSubsystem.EnvironmentAware,
    goroot: GoRoot,
) -> Process:
    input_digest, env_vars = await MultiGet(
        Get(Digest, MergeDigests([go_sdk_run.digest, request.input_digest])),
        Get(
            EnvironmentVars,
            EnvironmentVarsRequest(golang_env_aware.env_vars_to_pass_to_subprocesses),
        ),
    )

    env = {
        **env_vars,
        **request.env,
        GoSdkRunSetup.CHDIR_ENV: request.working_dir or "",
        "__PANTS_GO_SDK_CACHE_KEY": f"{goroot.full_version}/{goroot.goos}/{goroot.goarch}",
    }

    if "PATH" in env:
        env["PATH"] = f"{goroot.path}/bin:{env['PATH']}"

    if request.replace_sandbox_root_in_args:
        env[GoSdkRunSetup.SANDBOX_ROOT_ENV] = "1"

    # Disable the "coverage redesign" experiment on Go v1.20+ for now since Pants does not yet support it.
    if goroot.is_compatible_version("1.20") and not goroot.is_compatible_version("1.21"):
        exp_str = env.get("GOEXPERIMENT", "")
        exp_fields = exp_str.split(",") if exp_str != "" else []
        exp_fields = [exp for exp in exp_fields if exp != "coverageredesign"]
        if "nocoverageredesign" not in exp_fields:
            exp_fields.append("nocoverageredesign")
        env["GOEXPERIMENT"] = ",".join(exp_fields)

    return Process(
        argv=[bash.path, go_sdk_run.script.path, *request.command],
        env=env,
        input_digest=input_digest,
        description=request.description,
        output_files=request.output_files,
        output_directories=request.output_directories,
        immutable_input_digests={".goroot": goroot.digest},
        level=LogLevel.DEBUG,
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
