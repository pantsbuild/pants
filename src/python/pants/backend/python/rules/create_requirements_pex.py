# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules.download_pex_bin import DownloadedPexBin
from pants.backend.python.rules.hermetic_pex import HermeticPex
from pants.backend.python.subsystems.python_native_code import PexBuildEnvironment, PythonNativeCode
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.engine.fs import Digest
from pants.engine.isolated_process import ExecuteProcessResult, MultiPlatformExecuteProcessRequest
from pants.engine.platform import Platform, PlatformConstraint
from pants.engine.rules import optionable_rule, rule
from pants.engine.selectors import Get
from pants.util.objects import datatype, hashable_string_list, string_optional, string_type


class RequirementsPexRequest(datatype([
  ('output_filename', string_type),
  ('requirements', hashable_string_list),
  ('interpreter_constraints', hashable_string_list),
  ('entry_point', string_optional),
])):
  pass


class RequirementsPex(HermeticPex, datatype([('directory_digest', Digest)])):
  pass


# TODO: This is non-hermetic because the requirements will be resolved on the fly by
# pex, where it should be hermetically provided in some way.
@rule(
  RequirementsPex,
  [
    RequirementsPexRequest,
    DownloadedPexBin,
    PythonSetup,
    SubprocessEncodingEnvironment,
    PexBuildEnvironment,
    Platform
  ])
def create_requirements_pex(
  request,
  pex_bin,
  python_setup,
  subprocess_encoding_environment,
  pex_build_environment,
  platform
):
  """Returns a PEX with the given requirements, optional entry point, and optional
  interpreter constraints."""

  interpreter_constraint_args = []
  for constraint in request.interpreter_constraints:
    interpreter_constraint_args.extend(["--interpreter-constraint", constraint])

  argv = ["--output-file", request.output_filename]
  if request.entry_point is not None:
    argv.extend(["--entry-point", request.entry_point])
  argv.extend(interpreter_constraint_args + list(request.requirements))

  # NB: PEX outputs are platform dependent so in order to get a PEX that we can use locally, without
  # cross-building we specify that out PEX command be run on the current local platform. When we
  # support cross-building through CLI flags we can configure requests that build a PEX for out
  # local platform that are able to execute on a different platform, but for now in order to
  # guarantee correct build we need to restrict this command to execute on the same platform type
  # that the output is intended for. The correct way to interpret the keys
  # (execution_platform_constraint, target_platform_constraint) of this dictionary is "The output of
  # this command is intended for `target_platform_constraint` iff it is run on `execution_platform
  # constraint`".
  execute_process_request = MultiPlatformExecuteProcessRequest(
    {
      (PlatformConstraint(platform.value), PlatformConstraint(platform.value)):
        pex_bin.create_execute_request(
          python_setup=python_setup,
          subprocess_encoding_environment=subprocess_encoding_environment,
          pex_build_environment=pex_build_environment,
          pex_args=argv,
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
  yield RequirementsPex(directory_digest=result.output_directory_digest)


def rules():
  return [
    create_requirements_pex,
    optionable_rule(PythonSetup),
    optionable_rule(PythonNativeCode),
  ]
