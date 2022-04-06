# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Mapping, Optional, Tuple

from pants.backend.python.subsystems.python_native_code import PythonNativeCode
from pants.backend.python.util_rules import pex_environment
from pants.backend.python.util_rules.pex_environment import (
    PexEnvironment,
    PexRuntimeEnvironment,
    PythonExecutable,
)
from pants.core.util_rules import external_tool
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.engine.fs import CreateDigest, Digest, Directory, FileContent, MergeDigests
from pants.engine.internals.selectors import MultiGet
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessCacheScope
from pants.engine.rules import Get, collect_rules, rule
from pants.option.global_options import GlobalOptions
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import classproperty, frozen_after_init
from pants.util.strutil import create_path_env_var


class PexCli(TemplatedExternalTool):
    options_scope = "pex-cli"
    name = "pex"
    help = "The PEX (Python EXecutable) tool (https://github.com/pantsbuild/pex)."

    default_version = "v2.1.76"
    default_url_template = "https://github.com/pantsbuild/pex/releases/download/{version}/pex"
    version_constraints = ">=2.1.76,<3.0"

    @classproperty
    def default_known_versions(cls):
        return [
            "|".join(
                (
                    cls.default_version,
                    plat,
                    "71c9a67b7bf8ede5f1bdacbbc2bd3e3df4395499623d9d0d5dfee40ae38ab941",
                    "3731258",
                )
            )
            for plat in ["macos_arm64", "macos_x86_64", "linux_x86_64"]
        ]


@frozen_after_init
@dataclass(unsafe_hash=True)
class PexCliProcess:
    subcommand: tuple[str, ...]
    extra_args: tuple[str, ...]
    set_resolve_args: bool
    description: str = dataclasses.field(compare=False)
    additional_input_digest: Optional[Digest]
    extra_env: Optional[FrozenDict[str, str]]
    output_files: Optional[Tuple[str, ...]]
    output_directories: Optional[Tuple[str, ...]]
    python: Optional[PythonExecutable]
    level: LogLevel
    concurrency_available: int
    cache_scope: ProcessCacheScope

    def __init__(
        self,
        *,
        subcommand: Iterable[str],
        extra_args: Iterable[str],
        description: str,
        set_resolve_args: bool = True,
        additional_input_digest: Optional[Digest] = None,
        extra_env: Optional[Mapping[str, str]] = None,
        output_files: Optional[Iterable[str]] = None,
        output_directories: Optional[Iterable[str]] = None,
        python: Optional[PythonExecutable] = None,
        level: LogLevel = LogLevel.INFO,
        concurrency_available: int = 0,
        cache_scope: ProcessCacheScope = ProcessCacheScope.SUCCESSFUL,
    ) -> None:
        self.subcommand = tuple(subcommand)
        self.extra_args = tuple(extra_args)
        self.set_resolve_args = set_resolve_args
        self.description = description
        self.additional_input_digest = additional_input_digest
        self.extra_env = FrozenDict(extra_env) if extra_env else None
        self.output_files = tuple(output_files) if output_files else None
        self.output_directories = tuple(output_directories) if output_directories else None
        self.python = python
        self.level = level
        self.concurrency_available = concurrency_available
        self.cache_scope = cache_scope
        self.__post_init__()

    def __post_init__(self) -> None:
        if "--pex-root-path" in self.extra_args:
            raise ValueError("`--pex-root` flag not allowed. We set its value for you.")


class PexPEX(DownloadedExternalTool):
    """The Pex PEX binary."""


@rule
async def download_pex_pex(pex_cli: PexCli) -> PexPEX:
    pex_pex = await Get(
        DownloadedExternalTool, ExternalToolRequest, pex_cli.get_request(Platform.current)
    )
    return PexPEX(digest=pex_pex.digest, exe=pex_pex.exe)


@rule
async def setup_pex_cli_process(
    request: PexCliProcess,
    pex_pex: PexPEX,
    pex_env: PexEnvironment,
    python_native_code: PythonNativeCode,
    global_options: GlobalOptions,
    pex_runtime_env: PexRuntimeEnvironment,
) -> Process:
    tmpdir = ".tmp"
    gets: List[Get] = [Get(Digest, CreateDigest([Directory(tmpdir)]))]

    # The certs file will typically not be in the repo, so we can't digest it via a PathGlobs.
    # Instead we manually create a FileContent for it.
    cert_args = []
    if global_options.ca_certs_path:
        ca_certs_content = Path(global_options.ca_certs_path).read_bytes()
        chrooted_ca_certs_path = os.path.basename(global_options.ca_certs_path)

        gets.append(
            Get(
                Digest,
                CreateDigest((FileContent(chrooted_ca_certs_path, ca_certs_content),)),
            )
        )
        cert_args = ["--cert", chrooted_ca_certs_path]

    digests_to_merge = [pex_pex.digest]
    digests_to_merge.extend(await MultiGet(gets))
    if request.additional_input_digest:
        digests_to_merge.append(request.additional_input_digest)
    input_digest = await Get(Digest, MergeDigests(digests_to_merge))

    global_args = [
        # Ensure Pex and its subprocesses create temporary files in the the process execution
        # sandbox. It may make sense to do this generally for Processes, but in the short term we
        # have known use cases where /tmp is too small to hold large wheel downloads Pex is asked to
        # perform. Making the TMPDIR local to the sandbox allows control via
        # --local-execution-root-dir for the local case and should work well with remote cases where
        # a remoting implementation has to allow for processes producing large binaries in a
        # sandbox to support reasonable workloads. Communicating TMPDIR via --tmpdir instead of via
        # environment variable allows Pex to absolutize the path ensuring subprocesses that change
        # CWD can find the TMPDIR.
        "--tmpdir",
        tmpdir,
    ]

    if request.concurrency_available > 0:
        global_args.extend(["--jobs", "{pants_concurrency}"])

    if pex_runtime_env.verbosity > 0:
        global_args.append(f"-{'v' * pex_runtime_env.verbosity}")

    resolve_args = (
        [*cert_args, "--python-path", create_path_env_var(pex_env.interpreter_search_paths)]
        if request.set_resolve_args
        else []
    )
    args = [
        *global_args,
        *request.subcommand,
        *resolve_args,
        # NB: This comes at the end because it may use `--` passthrough args, # which must come at
        # the end.
        *request.extra_args,
    ]

    complete_pex_env = pex_env.in_sandbox(working_directory=None)
    normalized_argv = complete_pex_env.create_argv(pex_pex.exe, *args, python=request.python)
    env = {
        **complete_pex_env.environment_dict(python_configured=request.python is not None),
        **python_native_code.environment_dict,
        **(request.extra_env or {}),
        # If a subcommand is used, we need to use the `pex3` console script.
        **({"PEX_SCRIPT": "pex3"} if request.subcommand else {}),
    }

    return Process(
        normalized_argv,
        description=request.description,
        input_digest=input_digest,
        env=env,
        output_files=request.output_files,
        output_directories=request.output_directories,
        append_only_caches=complete_pex_env.append_only_caches,
        level=request.level,
        concurrency_available=request.concurrency_available,
        cache_scope=request.cache_scope,
    )


def rules():
    return [*collect_rules(), *external_tool.rules(), *pex_environment.rules()]
