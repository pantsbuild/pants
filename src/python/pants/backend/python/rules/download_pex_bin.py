# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

from pants.backend.python.rules.hermetic_pex import HermeticPex
from pants.backend.python.subsystems.python_native_code import PexBuildEnvironment
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalTool,
    ExternalToolRequest,
)
from pants.engine.fs import Digest
from pants.engine.platform import Platform
from pants.engine.process import Process
from pants.engine.rules import SubsystemRule, rule
from pants.engine.selectors import Get
from pants.python.python_setup import PythonSetup


class PexBin(ExternalTool):
    """The PEX (Python EXecutable) tool (https://github.com/pantsbuild/pex)."""

    options_scope = "download-pex-bin"
    name = "pex"
    default_version = "v2.1.24"
    default_known_versions = [
        f"v2.1.24|{plat}|561da5a7c76a8a88567a306fa60dfcb5c6924bb71c18b892080d5c2b3eea7133|2936466"
        for plat in ["darwin", "linux "]
    ]

    def generate_url(self, plat: Platform) -> str:
        return f"https://github.com/pantsbuild/pex/releases/download/{self.options.version}/pex"


@dataclass(frozen=True)
class DownloadedPexBin(HermeticPex):
    downloaded_tool: DownloadedExternalTool

    @property
    def executable(self) -> str:
        return self.downloaded_tool.exe

    @property
    def digest(self) -> Digest:
        """A directory digest containing the Pex executable."""
        return self.downloaded_tool.digest

    def create_process(  # type: ignore[override]
        self,
        python_setup: PythonSetup,
        subprocess_encoding_environment: SubprocessEncodingEnvironment,
        pex_build_environment: PexBuildEnvironment,
        *,
        pex_args: Iterable[str],
        description: str,
        input_digest: Optional[Digest] = None,
        env: Optional[Mapping[str, str]] = None,
        **kwargs: Any,
    ) -> Process:
        """Creates an Process that will run the pex CLI tool hermetically.

        :param python_setup: The parameters for selecting python interpreters to use when invoking
                             the pex tool.
        :param subprocess_encoding_environment: The locale settings to use for the pex tool
                                                invocation.
        :param pex_build_environment: The build environment for the pex tool.
        :param pex_args: The arguments to pass to the pex CLI tool.
        :param description: A description of the process execution to be performed.
        :param input_digest: The directory digest that contain the PEX CLI tool itself and any
                             input files it needs to run against. By default, this is just the
                             files that contain the PEX CLI tool itself. To merge in additional
                             files, include `self.digest` in a `MergeDigests` request.
        :param env: The environment to run the PEX in.
        :param kwargs: Any additional :class:`Process` kwargs to pass through.
        """

        pex_root_path = ".cache/pex_root"
        env = dict(env) if env else {}
        env.update(**pex_build_environment.invocation_environment_dict,)
        if "--pex-root" in pex_args:
            raise ValueError("--pex-root flag not allowed. We set its value for you.")
        pex_args = ("--pex-root", pex_root_path) + tuple(pex_args)

        return super().create_process(
            python_setup=python_setup,
            subprocess_encoding_environment=subprocess_encoding_environment,
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
    return [download_pex_bin, SubsystemRule(PexBin)]
