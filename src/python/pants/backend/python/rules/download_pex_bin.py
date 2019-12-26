# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from pants.backend.python.rules.hermetic_pex import HermeticPex
from pants.backend.python.subsystems.python_native_code import PexBuildEnvironment
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.engine.fs import Digest, SingleFileExecutable, Snapshot, UrlToFetch
from pants.engine.isolated_process import ExecuteProcessRequest
from pants.engine.rules import rule
from pants.engine.selectors import Get


@dataclass(frozen=True)
class DownloadedPexBin(HermeticPex):
  exe: SingleFileExecutable

  @property
  def executable(self) -> str:
    return self.exe.exe_filename

  @property
  def directory_digest(self) -> Digest:
    return self.exe.directory_digest

  def create_execute_request(  # type: ignore[override]
    self,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
    pex_build_environment: PexBuildEnvironment,
    *,
    pex_args: Iterable[str],
    description: str,
    input_files: Optional[Digest] = None,
    **kwargs: Any
  ) -> ExecuteProcessRequest:
    """Creates an ExecuteProcessRequest that will run the pex CLI tool hermetically.

    :param python_setup: The parameters for selecting python interpreters to use when invoking the
                         pex tool.
    :param subprocess_encoding_environment: The locale settings to use for the pex tool invocation.
    :param pex_build_environment: The build environment for the pex tool.
    :param pex_args: The arguments to pass to the pex CLI tool.
    :param description: A description of the process execution to be performed.
    :param input_files: The files that contain the pex CLI tool itself and any input files it needs
                        to run against. By default just the files that contain the pex CLI tool
                        itself. To merge in additional files, include the `directory_digest` in
                        `DirectoriesToMerge` request.
    :param kwargs: Any additional :class:`ExecuteProcessRequest` kwargs to pass through.
    """

    return super().create_execute_request(
      python_setup=python_setup,
      subprocess_encoding_environment=subprocess_encoding_environment,
      pex_path=self.executable,
      pex_args=["--disable-cache"] + list(pex_args),
      description=description,
      input_files=input_files or self.directory_digest,
      env=pex_build_environment.invocation_environment_dict,
      **kwargs
    )


@rule
async def download_pex_bin() -> DownloadedPexBin:
  # TODO: Inject versions and digests here through some option, rather than hard-coding it.
  url = 'https://github.com/pantsbuild/pex/releases/download/v1.6.12/pex'
  digest = Digest('ce64cb72cd23d2123dd48126af54ccf2b718d9ecb98c2ed3045ed1802e89e7e1', 1842359)
  snapshot = await Get[Snapshot](UrlToFetch(url, digest))
  return DownloadedPexBin(SingleFileExecutable(snapshot))


def rules():
  return [
    download_pex_bin,
  ]
