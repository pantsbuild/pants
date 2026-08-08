# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import hashlib
import re
import shlex
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
    CatBinary,
    CpBinary,
    MkdirBinary,
    PwdBinary,
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

_MODULE_CACHE_PARTITION_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}")

# Environment variables that decide where a module download comes from and whether its contents
# are checked, and so decide which downloads may share a module cache partition.
_MODULE_INTEGRITY_ENV_VARS = (
    "GOAUTH",
    "GOFLAGS",
    "GOINSECURE",
    "GONOPROXY",
    "GONOSUMDB",
    "GOPRIVATE",
    "GOPROXY",
    "GOSUMDB",
)


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

    module_cache_partition: str | None

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
        module_cache_partition: str | None = None,
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
        if module_cache_partition is not None and not _MODULE_CACHE_PARTITION_RE.fullmatch(
            module_cache_partition
        ):
            raise ValueError(
                "A module cache partition must be a short identifier of letters, digits, `_` and "
                "`-` starting with a letter or digit (it names a directory inside the shared "
                f"module cache), got {module_cache_partition!r}."
            )
        object.__setattr__(self, "module_cache_partition", module_cache_partition)
        if GoSdkRunSetup.FETCH_MODULE_ENV in self.env and module_cache_partition is None:
            # Without a partition there is no shared module cache, and the fetch step would look
            # for the downloaded module under a path that is never populated.
            raise ValueError(
                "Fetching a module through the shared module cache requires a "
                "`module_cache_partition`."
            )


@dataclass(frozen=True)
class GoSdkRunSetup:
    digest: Digest
    script: FileContent

    CHDIR_ENV = "__PANTS_CHDIR_TO"
    SANDBOX_ROOT_ENV = "__PANTS_REPLACE_SANDBOX_ROOT"
    MODCACHE_ENV = "__PANTS_GO_MODCACHE"
    FETCH_MODULE_ENV = "__PANTS_GO_FETCH_MODULE"


@rule
async def go_sdk_invoke_setup(
    goroot: GoRoot,
    cat: CatBinary,
    cp: CpBinary,
    mkdir: MkdirBinary,
    pwd: PwdBinary,
) -> GoSdkRunSetup:
    # Note: The `go` tool requires GOPATH to be an absolute path which can only be resolved
    # from within the execution sandbox. Thus, this code uses a bash script to be able to resolve
    # absolute paths inside the sandbox.
    cat_path = shlex.quote(cat.path)
    cp_path = shlex.quote(cp.path)
    mkdir_path = shlex.quote(mkdir.path)
    pwd_path = shlex.quote(pwd.path)
    go_run_script = FileContent(
        "__run_go.sh",
        textwrap.dedent(
            f"""\
            export GOROOT={goroot.path}
            # `-P` is explicit: `go` needs the resolved physical path, and the shell
            # builtin would otherwise hand back a logical path containing symlinks.
            sandbox_root="$({pwd_path} -P)"
            export GOPATH="${{sandbox_root}}/gopath"
            export GOCACHE="${{sandbox_root}}/cache"
            {mkdir_path} -p "$GOPATH" "$GOCACHE"
            modcache_partition="${GoSdkRunSetup.MODCACHE_ENV}"
            if [ -n "$modcache_partition" ]; then
              # The named cache is partitioned: each partition holds modules whose content
              # the caller has already pinned (see `module_cache_partition`). Two builds that
              # disagree about the bytes behind one module@version therefore never share a
              # cache entry, so a stale entry can never poison a later build.
              export GOMODCACHE="${{sandbox_root}}/__gomodcache/${{modcache_partition}}"
              export GOFLAGS="${{GOFLAGS:+${{GOFLAGS}} }}-modcacherw"
              {mkdir_path} -p "$GOMODCACHE"
            fi
            if [ -n "${GoSdkRunSetup.FETCH_MODULE_ENV}" ]; then
              module_version="${GoSdkRunSetup.FETCH_MODULE_ENV}"
              "{goroot.path}/bin/go" mod download -json "$module_version" > __module_metadata.json
              download_status=$?
              {cat_path} __module_metadata.json
              if [ "$download_status" -ne 0 ]; then
                exit "$download_status"
              fi
              # Parse the Dir/GoMod paths from the metadata with shell string operations only:
              # the sandbox PATH cannot be assumed to provide grep/sed.
              dir=""
              gomod=""
              while IFS= read -r line; do
                case "$line" in
                  *'"Dir": "'*) if [ -z "$dir" ]; then dir=${{line#*'"Dir": "'}}; dir=${{dir%'"'*}}; fi ;;
                  *'"GoMod": "'*) if [ -z "$gomod" ]; then gomod=${{line#*'"GoMod": "'}}; gomod=${{gomod%'"'*}}; fi ;;
                esac
              done < __module_metadata.json
              marker="__gomodcache/${{modcache_partition}}/"
              dir_rel="${{dir#*${{marker}}}}"
              gomod_rel="${{gomod#*${{marker}}}}"
              if [ -z "$dir" ] || [ -z "$gomod" ] || [ "$dir_rel" = "$dir" ] || [ "$gomod_rel" = "$gomod" ]; then
                echo "Failed to locate module $module_version under GOMODCACHE after download." 1>&2
                exit 1
              fi
              dest_dir="$GOPATH/pkg/mod/$dir_rel"
              dest_gomod="$GOPATH/pkg/mod/$gomod_rel"
              {mkdir_path} -p "$dest_dir" "${{dest_gomod%/*}}" || exit 1
              {cp_path} -Rp "$dir/." "$dest_dir/" || exit 1
              {cp_path} -p "$gomod" "$dest_gomod" || exit 1
              # Assert the copy produced the exact artifacts the Python rule will capture.
              if [ ! -f "$dest_gomod" ] || [ ! -d "$dest_dir" ]; then
                echo "Module $module_version was not copied into GOPATH/pkg/mod as expected." 1>&2
                exit 1
              fi
              exit 0
            fi
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
        # Pin toolchain selection so a go.mod/go.work `go` or `toolchain` directive that demands
        # a newer version fails fast with a clear message instead of silently downloading an
        # unfingerprinted toolchain (the default `GOTOOLCHAIN=auto` behaviour since Go 1.21).
        # Placement after **env_vars/**request.env is intentional: it prevents callers who pass
        # GOTOOLCHAIN via `[golang].subprocess_env_vars` from accidentally re-enabling switching.
        "GOTOOLCHAIN": "local",
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

    append_only_caches: dict[str, str] = {}
    if request.module_cache_partition is not None:
        # The caller's partition covers the checksums it expects, but where a module has no
        # recorded checksums the integrity of a download depends on the environment instead: which
        # proxy served it, and whether the checksum database was consulted at all. Builds
        # configuring those differently must not share downloads, so the environment is part of the
        # partition too.
        integrity_env = "\n".join(
            f"{name}={env[name]}" for name in _MODULE_INTEGRITY_ENV_VARS if name in env
        )
        integrity_fingerprint = hashlib.sha256(integrity_env.encode()).hexdigest()[:16]
        env[GoSdkRunSetup.MODCACHE_ENV] = (
            f"{request.module_cache_partition}-{integrity_fingerprint}"
        )
        append_only_caches["go_mod_cache"] = "__gomodcache"

    # Disable the "coverage redesign" experiment on Go v1.20+ for now since Pants does not yet support it.
    if goroot.is_compatible_version("1.20") and not goroot.is_compatible_version("1.25"):
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
        append_only_caches=append_only_caches,
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
