# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

from pants.backend.python.rules.hermetic_pex import HermeticPex
from pants.backend.python.subsystems.python_native_code import PexBuildEnvironment
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.binaries.binary_tool import BinaryToolFetchRequest, Script, ToolForPlatform, ToolVersion
from pants.binaries.binary_util import BinaryToolUrlGenerator
from pants.engine.fs import Digest, SingleFileExecutable, Snapshot
from pants.engine.isolated_process import Process
from pants.engine.platform import PlatformConstraint
from pants.engine.rules import rule, subsystem_rule
from pants.engine.selectors import Get
from pants.python.python_setup import PythonSetup


class PexBinUrlGenerator(BinaryToolUrlGenerator):
    def generate_urls(self, version, host_platform):
        return [f"https://github.com/pantsbuild/pex/releases/download/{version}/pex"]


@dataclass(frozen=True)
class DownloadedPexBin(HermeticPex):
    exe: SingleFileExecutable

    @property
    def executable(self) -> str:
        return self.exe.exe_filename

    @property
    def directory_digest(self) -> Digest:
        return self.exe.directory_digest

    class Factory(Script):
        options_scope = "download-pex-bin"
        name = "pex"
        default_version = "v2.1.9"

        # Note: You can compute the digest and size using:
        # curl -L https://github.com/pantsbuild/pex/releases/download/vX.Y.Z/pex | tee >(wc -c) >(shasum -a 256) >/dev/null
        default_versions_and_digests = {
            PlatformConstraint.none: ToolForPlatform(
                digest=Digest(
                    "4e2677ce7270dd04d767e93e1904c90aa8c7f4f53b76f3615215970b45d100d7", 2624111
                ),
                version=ToolVersion("v2.1.9"),
            ),
        }

        def get_external_url_generator(self):
            return PexBinUrlGenerator()

    def create_execute_request(  # type: ignore[override]
        self,
        python_setup: PythonSetup,
        subprocess_encoding_environment: SubprocessEncodingEnvironment,
        pex_build_environment: PexBuildEnvironment,
        *,
        pex_args: Iterable[str],
        description: str,
        input_files: Optional[Digest] = None,
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
        :param input_files: The files that contain the pex CLI tool itself and any input files it
                            needs to run against. By default just the files that contain the pex CLI
                            tool itself. To merge in additional files, include the
                            `directory_digest` in `DirectoriesToMerge` request.
        :param env: The environment to run the PEX in.
        :param kwargs: Any additional :class:`Process` kwargs to pass through.
        """

        env = dict(env) if env else {}
        env.update(**pex_build_environment.invocation_environment_dict,)

        return super().create_execute_request(
            python_setup=python_setup,
            subprocess_encoding_environment=subprocess_encoding_environment,
            pex_path=self.executable,
            pex_args=pex_args,
            description=description,
            input_files=input_files or self.directory_digest,
            env=env,
            **kwargs,
        )


@rule
async def download_pex_bin(pex_binary_tool: DownloadedPexBin.Factory) -> DownloadedPexBin:
    snapshot = await Get[Snapshot](BinaryToolFetchRequest(pex_binary_tool))
    return DownloadedPexBin(SingleFileExecutable(snapshot))


def rules():
    return [download_pex_bin, subsystem_rule(DownloadedPexBin.Factory)]
