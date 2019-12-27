# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
from dataclasses import dataclass
from pathlib import Path

from pants.binaries.binary_tool import BinaryToolFetchRequest, NativeTool
from pants.binaries.binary_util import BinaryToolUrlGenerator
from pants.engine.fs import (
  Digest,
  DirectoriesToMerge,
  FileContent,
  InputFilesContent,
  SingleFileExecutable,
)
from pants.engine.isolated_process import ExecuteProcessRequest
from pants.engine.platform import Platform
from pants.engine.rules import RootRule, optionable_rule, rule
from pants.engine.selectors import Get
from pants.util.memo import memoized_classproperty
from pants.util.strutil import ensure_relative_file_name


# FIXME: remove this url generator before merging! Should be using pantsbuild S3! Ensure this is
# uploaded to pantsbuild/binaries!
class BashUrlGenerator(BinaryToolUrlGenerator):

  def generate_urls(self, version, host_platform):
    bash_filename = host_platform.as_engine_platform().match({
      Platform.darwin: 'bash-osx',
      Platform.linux: 'bash-linux',
    })
    return [f'http://localhost:8000/{bash_filename}']


@dataclass(frozen=True)
class Bash:
  bash_exe: SingleFileExecutable

  class Factory(NativeTool):
    options_scope = 'bash-executable'
    name = 'bash'
    default_version = '5.0.0'

    @memoized_classproperty
    def default_digest(cls) -> Digest:
      return Platform.current.match({
        Platform.darwin: Digest('122070d14cb26ddc3205e3de126aedb333d2ef3fa18f3733f24b28ca88b9ec66',
                                1366356),
        Platform.linux: Digest('f788b8bdeddc85541d06b9713d071b2373b30f622372b07932a6908103198dbc',
                               4661456)
      })

    def get_external_url_generator(self):
      return BashUrlGenerator()

  @property
  def exe_relpath(self) -> Path:
    return self.bash_exe.exe_filename

  @property
  def exe_digest(self) -> Digest:
    return self.bash_exe.directory_digest


@rule
async def get_bash(bash_binary_tool: Bash.Factory) -> Bash:
  exe = await Get[SingleFileExecutable](BinaryToolFetchRequest(bash_binary_tool))
  return Bash(exe)


@dataclass(frozen=True)
class BashScriptRequest:
  script: FileContent
  base_exe_request: ExecuteProcessRequest


@rule
async def create_bash_script_execution_request(req: BashScriptRequest, bash: Bash) -> ExecuteProcessRequest:
  bash_script_digest = await Get[Digest](InputFilesContent((req.script,)))
  base_digest = req.base_exe_request.input_files

  merged_digest = await Get[Digest](DirectoriesToMerge((
    bash.exe_digest,
    bash_script_digest,
    base_digest,
  )))

  full_argv = [
    ensure_relative_file_name(bash.exe_relpath),
    req.script.path,
    *req.base_exe_request.argv,
  ]

  return dataclasses.replace(
    req.base_exe_request,
    argv=tuple(full_argv),
    input_files=merged_digest)


def rules():
  return [
    optionable_rule(Bash.Factory),
    get_bash,
    RootRule(BashScriptRequest),
    create_bash_script_execution_request,
  ]
