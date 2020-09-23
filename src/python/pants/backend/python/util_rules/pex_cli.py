# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Mapping, Optional, Tuple

from pants.backend.python.subsystems.python_native_code import PythonNativeCode
from pants.backend.python.util_rules import pex_environment
from pants.backend.python.util_rules.pex_environment import PexEnvironment, PythonExecutable
from pants.core.util_rules import external_tool
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalTool,
    ExternalToolRequest,
)
from pants.engine.fs import CreateDigest, Digest, Directory, FileContent, MergeDigests
from pants.engine.internals.selectors import MultiGet
from pants.engine.platform import Platform
from pants.engine.process import Process
from pants.engine.rules import Get, collect_rules, rule
from pants.option.global_options import GlobalOptions
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import classproperty, frozen_after_init


class PexBinary(ExternalTool):
    """The PEX (Python EXecutable) tool (https://github.com/pantsbuild/pex)."""

    options_scope = "download-pex-bin"
    name = "pex"
    default_version = "v2.1.16"

    @classproperty
    def default_known_versions(cls):
        return [
            "|".join(
                (
                    cls.default_version,
                    plat,
                    "38712847654254088a23394728f9a5fb93c6c83631300e7ab427ec780a88f653",
                    "2662638",
                )
            )
            for plat in ["darwin", "linux"]
        ]

    def generate_url(self, _: Platform) -> str:
        return f"https://github.com/pantsbuild/pex/releases/download/{self.version}/pex"

    def generate_exe(self, _: Platform) -> str:
        return "./pex"


@frozen_after_init
@dataclass(unsafe_hash=True)
class PexCliProcess:
    argv: Tuple[str, ...]
    description: str = dataclasses.field(compare=False)
    additional_input_digest: Optional[Digest]
    extra_env: Optional[FrozenDict[str, str]]
    output_files: Optional[Tuple[str, ...]]
    output_directories: Optional[Tuple[str, ...]]
    python: Optional[PythonExecutable]
    level: LogLevel

    def __init__(
        self,
        *,
        argv: Iterable[str],
        description: str,
        additional_input_digest: Optional[Digest] = None,
        extra_env: Optional[Mapping[str, str]] = None,
        output_files: Optional[Iterable[str]] = None,
        output_directories: Optional[Iterable[str]] = None,
        python: Optional[PythonExecutable] = None,
        level: LogLevel = LogLevel.INFO,
    ) -> None:
        self.argv = tuple(argv)
        self.description = description
        self.additional_input_digest = additional_input_digest
        self.extra_env = FrozenDict(extra_env) if extra_env else None
        self.output_files = tuple(output_files) if output_files else None
        self.output_directories = tuple(output_directories) if output_directories else None
        self.python = python
        self.level = level
        self.__post_init__()

    def __post_init__(self) -> None:
        if "--pex-root-path" in self.argv:
            raise ValueError("`--pex-root` flag not allowed. We set its value for you.")


@rule
async def setup_pex_cli_process(
    request: PexCliProcess,
    pex_binary: PexBinary,
    pex_env: PexEnvironment,
    python_native_code: PythonNativeCode,
    global_options: GlobalOptions,
) -> Process:
    tmpdir = ".tmp"
    gets: List[Get] = [
        Get(DownloadedExternalTool, ExternalToolRequest, pex_binary.get_request(Platform.current)),
        Get(Digest, CreateDigest([Directory(f"{tmpdir}/.reserve")])),
    ]
    cert_args = []

    # The certs file will typically not be in the repo, so we can't digest it via a PathGlobs.
    # Instead we manually create a FileContent for it.
    if global_options.options.ca_certs_path:
        ca_certs_content = Path(global_options.options.ca_certs_path).read_bytes()
        chrooted_ca_certs_path = os.path.join(
            os.path.basename(global_options.options.ca_certs_path)
        )
        gets.append(
            Get(
                Digest,
                CreateDigest(
                    (FileContent(chrooted_ca_certs_path, ca_certs_content, is_executable=False),)
                ),
            )
        )
        cert_args = ["--cert", chrooted_ca_certs_path]

    downloaded_pex_bin, *digests_to_merge = await MultiGet(gets)
    digests_to_merge.append(downloaded_pex_bin.digest)
    if request.additional_input_digest:
        digests_to_merge.append(request.additional_input_digest)
    input_digest = await Get(Digest, MergeDigests(digests_to_merge))

    pex_root_path = ".cache/pex_root"
    argv = pex_env.create_argv(
        downloaded_pex_bin.exe,
        *request.argv,
        *cert_args,
        "--pex-root",
        pex_root_path,
        python=request.python,
    )
    env = {
        # Ensure Pex and its subprocesses create temporary files in the the process execution
        # sandbox. It may make sense to do this generally for Processes, but in the short term we
        # have known use cases where /tmp is too small to hold large wheel downloads Pex is asked to
        # perform. Making the TMPDIR local to the sandbox allows control via
        # --local-execution-root-dir for the local case and should work well with remote cases where
        # a remoting implementation has to allow for processes producing large binaries in a
        # sandbox to support reasonable workloads.
        "TMPDIR": tmpdir,
        **pex_env.environment_dict(python_configured=request.python is not None),
        **python_native_code.environment_dict,
        **(request.extra_env or {}),
    }

    return Process(
        argv,
        description=request.description,
        input_digest=input_digest,
        env=env,
        output_files=request.output_files,
        output_directories=request.output_directories,
        append_only_caches={"pex_root": pex_root_path},
        level=request.level,
    )


def rules():
    return [*collect_rules(), *external_tool.rules(), *pex_environment.rules()]
