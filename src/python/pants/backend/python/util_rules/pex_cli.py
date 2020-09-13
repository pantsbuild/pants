# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Tuple

from pants.backend.python.subsystems.python_native_code import PythonNativeCode
from pants.backend.python.util_rules import pex_environment
from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.core.util_rules import external_tool
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalTool,
    ExternalToolRequest,
)
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.internals.selectors import MultiGet
from pants.engine.platform import Platform
from pants.engine.process import Process
from pants.engine.rules import Get, collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.meta import frozen_after_init


class PexBinary(ExternalTool):
    """The PEX (Python EXecutable) tool (https://github.com/pantsbuild/pex)."""

    options_scope = "download-pex-bin"
    name = "pex"
    default_version = "v2.1.14"
    default_known_versions = [
        f"v2.1.14|{plat}|12937da9ad5ad2c60564aa35cb4b3992ba3cc5ef7efedd44159332873da6fe46|2637138"
        for plat in ["darwin", "linux "]
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

    def __init__(
        self,
        *,
        argv: Iterable[str],
        description: str,
        additional_input_digest: Optional[Digest] = None,
        extra_env: Optional[Mapping[str, str]] = None,
        output_files: Optional[Iterable[str]] = None,
        output_directories: Optional[Iterable[str]] = None,
    ) -> None:
        self.argv = tuple(argv)
        self.description = description
        self.additional_input_digest = additional_input_digest
        self.extra_env = FrozenDict(extra_env) if extra_env else None
        self.output_files = tuple(output_files) if output_files else None
        self.output_directories = tuple(output_directories) if output_directories else None
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
) -> Process:
    tmpdir = ".tmp"
    downloaded_pex_bin, tmp_dir_digest = await MultiGet(
        Get(DownloadedExternalTool, ExternalToolRequest, pex_binary.get_request(Platform.current)),
        # TODO(John Sirois): Use a Directory instead of this FileContent hack when a fix for
        #  https://github.com/pantsbuild/pants/issues/9650 lands.
        Get(Digest, CreateDigest([FileContent(f"{tmpdir}/.reserve", b"")])),
    )

    digests_to_merge = [downloaded_pex_bin.digest, tmp_dir_digest]
    if request.additional_input_digest:
        digests_to_merge.append(request.additional_input_digest)
    input_digest = await Get(Digest, MergeDigests(digests_to_merge))

    pex_root_path = ".cache/pex_root"
    argv = pex_env.create_argv(downloaded_pex_bin.exe, *request.argv, "--pex-root", pex_root_path)
    env = {
        # Ensure Pex and its subprocesses create temporary files in the the process execution
        # sandbox. It may make sense to do this generally for Processes, but in the short term we
        # have known use cases where /tmp is too small to hold large wheel downloads Pex is asked to
        # perform. Making the TMPDIR local to the sandbox allows control via
        # --local-execution-root-dir for the local case and should work well with remote cases where
        # a remoting implementation has to allow for processes producing large binaries in a
        # sandbox to support reasonable workloads.
        "TMPDIR": tmpdir,
        **pex_env.environment_dict,
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
    )


def rules():
    return [*collect_rules(), *external_tool.rules(), *pex_environment.rules()]
