# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.python.rules.download_pex_bin import DownloadedPexBin
from pants.backend.python.rules.hermetic_pex import HermeticPex
from pants.backend.python.subsystems.python_native_code import PexBuildEnvironment
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.engine.fs import (
  EMPTY_DIRECTORY_DIGEST,
  Digest,
  DirectoriesToMerge,
  DirectoryWithPrefixToAdd,
)
from pants.engine.isolated_process import ExecuteProcessResult, MultiPlatformExecuteProcessRequest
from pants.engine.platform import PlatformConstraint
from pants.engine.rules import optionable_rule, rule
from pants.engine.selectors import Get


@dataclass(frozen=True)
class CreatePex:
  """Represents a generic request to create a PEX from its inputs."""
  output_filename: str
  requirements: Tuple[str] = ()
  interpreter_constraints: Tuple[str] = ()
  entry_point: Optional[str] = None
  input_files_digest: Optional[Digest] = None


@dataclass(frozen=True)
class Pex(HermeticPex):
  """Wrapper for a digest containing a pex file created with some filename."""
  directory_digest: Digest


# TODO: This is non-hermetic because the requirements will be resolved on the fly by
# pex, where it should be hermetically provided in some way.
@rule
def create_pex(
    request: CreatePex,
    pex_bin: DownloadedPexBin,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
    pex_build_environment: PexBuildEnvironment,
    platform: PlatformConstraint
) -> Pex:
  """Returns a PEX with the given requirements, optional entry point, and optional
  interpreter constraints."""

  # ignore none constraint if some rule pushes a constraint down as none.
  if platform == PlatformConstraint.none:
    platform = PlatformConstraint.local_platform

  interpreter_constraint_args = []
  for constraint in request.interpreter_constraints:
    interpreter_constraint_args.extend(["--interpreter-constraint", constraint])

  argv = ["--output-file", request.output_filename]
  if request.entry_point is not None:
    argv.extend(["--entry-point", request.entry_point])
  argv.extend(interpreter_constraint_args + list(request.requirements))

  source_dir_name = 'source_files'

  argv.append(f'--sources-directory={source_dir_name}')
  sources_digest = request.input_files_digest if request.input_files_digest else EMPTY_DIRECTORY_DIGEST
  sources_digest_as_subdir = yield Get(Digest, DirectoryWithPrefixToAdd(sources_digest, source_dir_name))
  all_inputs = (pex_bin.directory_digest, sources_digest_as_subdir,)
  merged_digest = yield Get(Digest, DirectoriesToMerge(directories=all_inputs))

  # NB: PEX outputs are platform dependent so in order to get a PEX that we can use locally, without
  # cross-building, we specify that our PEX command be run on the current local platform. When we
  # support cross-building through CLI flags we can configure requests that build a PEX for out
  # local platform that are able to execute on a different platform, but for now in order to
  # guarantee correct build we need to restrict this command to execute on the same platform type
  # that the output is intended for. The correct way to interpret the keys
  # (execution_platform_constraint, target_platform_constraint) of this dictionary is "The output of
  # this command is intended for `target_platform_constraint` iff it is run on `execution_platform
  # constraint`".
  execute_process_request = MultiPlatformExecuteProcessRequest(
    {
      (platform, platform):
        pex_bin.create_execute_request(
          python_setup=python_setup,
          subprocess_encoding_environment=subprocess_encoding_environment,
          pex_build_environment=pex_build_environment,
          pex_args=argv,
          input_files=merged_digest,
          description=f"Create a requirements PEX: {', '.join(request.requirements)}",
          output_files=(request.output_filename,)
        )
    }
  )

  result = yield Get(
    ExecuteProcessResult,
    MultiPlatformExecuteProcessRequest,
    execute_process_request
  )
  yield Pex(directory_digest=result.output_directory_digest)


def rules():
  return [
    create_pex,
    optionable_rule(PythonSetup),
  ]
