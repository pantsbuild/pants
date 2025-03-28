# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
import os.path
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from pants.backend.python.subsystems.python_native_code import PythonNativeCodeSubsystem
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.util_rules import pex_environment
from pants.backend.python.util_rules.pex_environment import PexEnvironment, PexSubsystem
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules import adhoc_binaries, external_tool
from pants.core.util_rules.adhoc_binaries import PythonBuildStandaloneBinary
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.engine.fs import CreateDigest, Digest, Directory, MergeDigests
from pants.engine.internals.selectors import MultiGet
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessCacheScope
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobalOptions, ca_certs_path_to_file_content
from pants.option.option_types import ArgsListOption
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class PexCli(TemplatedExternalTool):
    options_scope = "pex-cli"
    name = "pex"
    help = "The PEX (Python EXecutable) tool (https://github.com/pex-tool/pex)."

    default_version = "v2.33.7"
    default_url_template = "https://github.com/pex-tool/pex/releases/download/{version}/pex"
    version_constraints = ">=2.13.0,<3.0"

    # extra args to be passed to the pex tool; note that they
    # are going to apply to all invocations of the pex tool.
    global_args = ArgsListOption(
        example="--check=error --no-compile",
        extra_help=softwrap(
            """
            Note that these apply to all invocations of the pex tool, including building `pex_binary`
            targets, preparing `python_test` targets to run, and generating lockfiles.
            """
        ),
    )

    default_known_versions = [
        "v2.33.7|macos_x86_64|9224dd68c3b95f3c9d42818181bbbfd6e307ca828f9c1c24508a004d63984ce5|4591206",
        "v2.33.7|macos_arm64|9224dd68c3b95f3c9d42818181bbbfd6e307ca828f9c1c24508a004d63984ce5|4591206",
        "v2.33.7|linux_x86_64|9224dd68c3b95f3c9d42818181bbbfd6e307ca828f9c1c24508a004d63984ce5|4591206",
        "v2.33.7|linux_arm64|9224dd68c3b95f3c9d42818181bbbfd6e307ca828f9c1c24508a004d63984ce5|4591206",
        "v2.33.4|macos_x86_64|d6a4041d52732ea0a323db2bea3e6a5995391fed3bc1f2b81d84ee0bcbc16e7c|4589638",
        "v2.33.4|macos_arm64|d6a4041d52732ea0a323db2bea3e6a5995391fed3bc1f2b81d84ee0bcbc16e7c|4589638",
        "v2.33.4|linux_x86_64|d6a4041d52732ea0a323db2bea3e6a5995391fed3bc1f2b81d84ee0bcbc16e7c|4589638",
        "v2.33.4|linux_arm64|d6a4041d52732ea0a323db2bea3e6a5995391fed3bc1f2b81d84ee0bcbc16e7c|4589638",
        "v2.33.1|macos_x86_64|5ebed0e2ba875983a72b4715ee3b2ca6ae5fedbf28d738634e02e30e3bb5ed28|4559974",
        "v2.33.1|macos_arm64|5ebed0e2ba875983a72b4715ee3b2ca6ae5fedbf28d738634e02e30e3bb5ed28|4559974",
        "v2.33.1|linux_x86_64|5ebed0e2ba875983a72b4715ee3b2ca6ae5fedbf28d738634e02e30e3bb5ed28|4559974",
        "v2.33.1|linux_arm64|5ebed0e2ba875983a72b4715ee3b2ca6ae5fedbf28d738634e02e30e3bb5ed28|4559974",
    ]


@dataclass(frozen=True)
class PexCliProcess:
    subcommand: tuple[str, ...]
    extra_args: tuple[str, ...]
    description: str = dataclasses.field(compare=False)
    additional_input_digest: Digest | None
    extra_env: FrozenDict[str, str] | None
    output_files: tuple[str, ...] | None
    output_directories: tuple[str, ...] | None
    level: LogLevel
    concurrency_available: int
    cache_scope: ProcessCacheScope

    def __init__(
        self,
        *,
        subcommand: Iterable[str],
        extra_args: Iterable[str],
        description: str,
        additional_input_digest: Digest | None = None,
        extra_env: Mapping[str, str] | None = None,
        output_files: Iterable[str] | None = None,
        output_directories: Iterable[str] | None = None,
        level: LogLevel = LogLevel.INFO,
        concurrency_available: int = 0,
        cache_scope: ProcessCacheScope = ProcessCacheScope.SUCCESSFUL,
    ) -> None:
        object.__setattr__(self, "subcommand", tuple(subcommand))
        object.__setattr__(self, "extra_args", tuple(extra_args))
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "additional_input_digest", additional_input_digest)
        object.__setattr__(self, "extra_env", FrozenDict(extra_env) if extra_env else None)
        object.__setattr__(self, "output_files", tuple(output_files) if output_files else None)
        object.__setattr__(
            self, "output_directories", tuple(output_directories) if output_directories else None
        )
        object.__setattr__(self, "level", level)
        object.__setattr__(self, "concurrency_available", concurrency_available)
        object.__setattr__(self, "cache_scope", cache_scope)

        self.__post_init__()

    def __post_init__(self) -> None:
        if "--pex-root-path" in self.extra_args:
            raise ValueError("`--pex-root` flag not allowed. We set its value for you.")


class PexPEX(DownloadedExternalTool):
    """The Pex PEX binary."""


@rule
async def download_pex_pex(pex_cli: PexCli, platform: Platform) -> PexPEX:
    pex_pex = await Get(DownloadedExternalTool, ExternalToolRequest, pex_cli.get_request(platform))
    return PexPEX(digest=pex_pex.digest, exe=pex_pex.exe)


@rule
async def setup_pex_cli_process(
    request: PexCliProcess,
    pex_pex: PexPEX,
    pex_env: PexEnvironment,
    bootstrap_python: PythonBuildStandaloneBinary,
    python_native_code: PythonNativeCodeSubsystem.EnvironmentAware,
    global_options: GlobalOptions,
    pex_subsystem: PexSubsystem,
    pex_cli_subsystem: PexCli,
    python_setup: PythonSetup,
) -> Process:
    tmpdir = ".tmp"
    gets: list[Get] = [Get(Digest, CreateDigest([Directory(tmpdir)]))]

    cert_args = []
    if global_options.ca_certs_path:
        ca_certs_fc = ca_certs_path_to_file_content(global_options.ca_certs_path)
        gets.append(Get(Digest, CreateDigest((ca_certs_fc,))))
        cert_args = ["--cert", ca_certs_fc.path]

    digests_to_merge = [pex_pex.digest]
    digests_to_merge.extend(await MultiGet(gets))
    if request.additional_input_digest:
        digests_to_merge.append(request.additional_input_digest)
    input_digest = await Get(Digest, MergeDigests(digests_to_merge))

    global_args = [
        # Ensure Pex and its subprocesses create temporary files in the process execution
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

    verbosity_args = [f"-{'v' * pex_subsystem.verbosity}"] if pex_subsystem.verbosity > 0 else []

    warnings_args = [] if pex_subsystem.emit_warnings else ["--no-emit-warnings"]

    # NB: We should always pass `--python-path`, as that tells Pex where to look for interpreters
    # when `--python` isn't an absolute path.
    resolve_args = [
        *cert_args,
        "--python-path",
        os.pathsep.join(pex_env.interpreter_search_paths),
    ]
    # All old-style pex runs take the --pip-version flag, but only certain subcommands of the
    # `pex3` console script do. So if invoked with a subcommand, the caller must selectively
    # set --pip-version only on subcommands that take it.
    pip_version_args = [] if request.subcommand else ["--pip-version", python_setup.pip_version]
    args = [
        *request.subcommand,
        *global_args,
        *verbosity_args,
        *warnings_args,
        *pip_version_args,
        *resolve_args,
        *pex_cli_subsystem.global_args,
        # NB: This comes at the end because it may use `--` passthrough args, # which must come at
        # the end.
        *request.extra_args,
    ]

    complete_pex_env = pex_env.in_sandbox(working_directory=None)
    normalized_argv = complete_pex_env.create_argv(pex_pex.exe, *args)
    env = {
        **complete_pex_env.environment_dict(python=bootstrap_python),
        **python_native_code.subprocess_env_vars,
        **(request.extra_env or {}),  # type: ignore[dict-item]
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


def maybe_log_pex_stderr(stderr: bytes, pex_verbosity: int) -> None:
    """Forward Pex's stderr to a Pants logger if conditions are met."""
    log_output = stderr.decode()
    if log_output and "PEXWarning:" in log_output:
        logger.warning("%s", log_output)
    elif log_output and pex_verbosity > 0:
        logger.info("%s", log_output)


def rules():
    return [
        *collect_rules(),
        *external_tool.rules(),
        *pex_environment.rules(),
        *adhoc_binaries.rules(),
        UnionRule(ExportableTool, PexCli),
    ]
