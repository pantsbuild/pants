# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

from pants.backend.python.rules.hermetic_pex import HermeticPex, PexEnvironment
from pants.backend.python.subsystems.python_native_code import PythonNativeCode
from pants.backend.python.subsystems.subprocess_environment import SubprocessEnvironment
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalTool,
    ExternalToolRequest,
)
from pants.engine.fs import Digest
from pants.engine.platform import Platform
from pants.engine.process import Process
from pants.engine.rules import Get, collect_rules, rule


class PexBin(ExternalTool):
    """The PEX (Python EXecutable) tool (https://www.pantsbuild.org/docs/pex-files)."""

    options_scope = "download-pex-bin"
    name = "pex"
    default_version = "v2.1.15"
    default_known_versions = [
        f"v2.1.15|{plat}|f566d1a6d66c7427df3ce7c1c44f2242130133177b885bcd4024b777420d69a6|2637459"
        for plat in ["darwin", "linux "]
    ]

    def generate_url(self, _: Platform) -> str:
        return f"https://github.com/pantsbuild/pex/releases/download/{self.version}/pex"

    def generate_exe(self, _: Platform) -> str:
        return "./pex"


@dataclass(frozen=True)
class DownloadedPexBin(HermeticPex):
    downloaded_tool: DownloadedExternalTool

    @property
    def executable(self) -> str:
        return f"{self.downloaded_tool.exe}"

    @property
    def digest(self) -> Digest:
        """A directory digest containing the Pex executable."""
        return self.downloaded_tool.digest

    def create_process(  # type: ignore[override]
        self,
        pex_environment: PexEnvironment,
        subprocess_environment: SubprocessEnvironment,
        python_native_code: PythonNativeCode,
        *,
        pex_args: Iterable[str],
        description: str,
        input_digest: Optional[Digest] = None,
        env: Optional[Mapping[str, str]] = None,
        **kwargs: Any,
    ) -> Process:
        """Creates an Process that will run the pex CLI tool hermetically.

        :param pex_environment: The environment needed to bootstrap the PEX runtime.
        :param subprocess_environment: The locale settings to use for the pex tool
            invocation.
        :param python_native_code: The build environment for the pex tool.
        :param pex_args: The arguments to pass to the pex CLI tool.
        :param description: A description of the process execution to be performed.
        :param input_digest: The directory digest that contain the PEX CLI tool itself and any
            input files it needs to run against. By default, this is just the files that contain
            the PEX CLI tool itself. To merge in additional files, include `self.digest` in a
            `MergeDigests` request.
        :param env: The environment to run the PEX in.
        :param kwargs: Any additional :class:`Process` kwargs to pass through.
        """

        pex_root_path = ".cache/pex_root"
        env = {**(env or {}), **python_native_code.environment_dict}
        if "--pex-root" in pex_args:
            raise ValueError("--pex-root flag not allowed. We set its value for you.")
        pex_args = ("--pex-root", pex_root_path) + tuple(pex_args)

        return super().create_process(
            pex_environment=pex_environment,
            subprocess_environment=subprocess_environment,
            pex_path=self.executable,
            pex_args=pex_args,
            description=description,
            input_digest=input_digest or self.digest,
            env=env,
            append_only_caches={"pex_root": pex_root_path},
            **kwargs,
        )


@rule
async def download_pex_bin(pex_binary_tool: PexBin) -> DownloadedPexBin:
    downloaded_tool = await Get(
        DownloadedExternalTool, ExternalToolRequest, pex_binary_tool.get_request(Platform.current)
    )
    return DownloadedPexBin(downloaded_tool)


def rules():
    return collect_rules()
