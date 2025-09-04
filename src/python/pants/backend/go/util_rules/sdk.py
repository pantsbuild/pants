# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import textwrap
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from pants.backend.go.subsystems.golang import GolangSubsystem
from pants.backend.go.util_rules import goroot
from pants.backend.go.util_rules.go_bootstrap import GoBootstrap
from pants.backend.go.util_rules.goroot import GoRoot
from pants.core.util_rules.env_vars import environment_vars_subset
from pants.core.util_rules.system_binaries import (
    BashBinary,
    BinaryShimsRequest,
    create_binary_shims,
)
from pants.engine.env_vars import EnvironmentVarsRequest
from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import create_digest, merge_digests
from pants.engine.process import Process, fallible_to_exec_result_or_raise
from pants.engine.rules import collect_rules, implicitly, rule
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
    go_run_script = FileContent(
        "__run_go.sh",
        textwrap.dedent(
            f"""\
            export GOROOT={goroot.path}
            sandbox_root="$(/bin/pwd)"
            export GOPATH="${{sandbox_root}}/gopath"
            export GOCACHE="${{sandbox_root}}/cache"
            /bin/mkdir -p "$GOPATH" "$GOCACHE"
            if [ -n "${GoSdkRunSetup.CHDIR_ENV}" ]; then
              cd "${GoSdkRunSetup.CHDIR_ENV}"
            fi
            if [ -n "${GoSdkRunSetup.SANDBOX_ROOT_ENV}" ]; then
              export __PANTS_SANDBOX_ROOT__="$sandbox_root"
              args=("${{@//__PANTS_SANDBOX_ROOT__/$sandbox_root}}")
              set -- "${{args[@]}}"
            fi
            exec "{goroot.path}/bin/go" "$@"
            """
        ).encode("utf-8"),
    )

    digest = await create_digest(CreateDigest([go_run_script]))
    return GoSdkRunSetup(digest, go_run_script)


@rule
async def setup_go_sdk_process(
    request: GoSdkProcess,
    go_bootstrap: GoBootstrap,
    go_sdk_run: GoSdkRunSetup,
    bash: BashBinary,
    golang_env_aware: GolangSubsystem.EnvironmentAware,
    goroot: GoRoot,
) -> Process:
    # Use go search path to find extra tools
    search_path = go_bootstrap.go_search_paths

    input_digest, env_vars = await concurrently(
        merge_digests(MergeDigests([go_sdk_run.digest, request.input_digest])),
        environment_vars_subset(
            EnvironmentVarsRequest(golang_env_aware.env_vars_to_pass_to_subprocesses),
            **implicitly(),
        ),
    )

    env = {
        **env_vars,
        **request.env,
        GoSdkRunSetup.CHDIR_ENV: request.working_dir or "",
        "__PANTS_GO_SDK_CACHE_KEY": f"{goroot.full_version}/{goroot.goos}/{goroot.goarch}",
    }

    immutable_input_digests: dict[str, Digest] = {}

    # Add path to additional tools, such as git, that may be needed by the go tool
    if golang_env_aware.extra_tools:
        extra_tools = await create_binary_shims(
            BinaryShimsRequest.for_binaries(
                *golang_env_aware.extra_tools,
                rationale="allow additional tools for go tools",
                search_path=search_path,
            ),
            bash,
        )
        # Prepend path to additional tools
        if "PATH" in env:
            env["PATH"] = f"{extra_tools.path_component}:{env['PATH']}"
        else:
            env["PATH"] = extra_tools.path_component
        immutable_input_digests.update(extra_tools.immutable_input_digests)

    if request.replace_sandbox_root_in_args:
        env[GoSdkRunSetup.SANDBOX_ROOT_ENV] = "1"

    # Disable the "coverage redesign" experiment on Go v1.20+ for now since Pants does not yet support it.
    if goroot.is_compatible_version("1.20"):
        exp_str = env.get("GOEXPERIMENT", "")
        exp_fields = exp_str.split(",") if exp_str != "" else []
        exp_fields = [exp for exp in exp_fields if exp != "coverageredesign"]
        if "nocoverageredesign" not in exp_fields:
            exp_fields.append("nocoverageredesign")
        env["GOEXPERIMENT"] = ",".join(exp_fields)

    return Process(
        argv=[bash.path, go_sdk_run.script.path, *request.command],
        env=env,
        immutable_input_digests=immutable_input_digests,
        input_digest=input_digest,
        description=request.description,
        output_files=request.output_files,
        output_directories=request.output_directories,
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
    result = await fallible_to_exec_result_or_raise(
        **implicitly(
            GoSdkProcess(
                ["tool", request.tool_name, "-V=full"],
                description=f"Obtain tool ID for Go tool `{request.tool_name}`.",
            )
        )
    )
    return GoSdkToolIDResult(tool_name=request.tool_name, tool_id=result.stdout.decode().strip())


def rules():
    return (*collect_rules(), *goroot.rules())
