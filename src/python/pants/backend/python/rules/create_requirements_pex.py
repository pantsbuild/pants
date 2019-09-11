# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules.download_pex_bin import DownloadedPexBin
from pants.backend.python.subsystems.python_native_code import PexBuildEnvironment, PythonNativeCode
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.engine.fs import Digest
from pants.engine.isolated_process import (ExecuteProcessRequest, ExecuteProcessResult,
                                           MultiPlatformExecuteProcessRequest)
from pants.engine.platform import Platform, PlatformConstraint
from pants.engine.rules import optionable_rule, rule
from pants.engine.selectors import Get
from pants.util.objects import datatype, hashable_string_list, string_optional, string_type
from pants.util.strutil import create_path_env_var


class RequirementsPexRequest(datatype([
  ('output_filename', string_type),
  ('requirements', hashable_string_list),
  ('interpreter_constraints', hashable_string_list),
  ('entry_point', string_optional),
])):
  pass


class RequirementsPex(datatype([('directory_digest', Digest)])):
  pass


# TODO: This is non-hermetic because the requirements will be resolved on the fly by
# pex, where it should be hermetically provided in some way.
@rule(RequirementsPex, [RequirementsPexRequest, DownloadedPexBin, PythonSetup, PexBuildEnvironment, Platform])
def create_requirements_pex(request, pex_bin, python_setup, pex_build_environment, platform):
  """Returns a PEX with the given requirements, optional entry point, and optional
  interpreter constraints."""

  interpreter_search_paths = create_path_env_var(python_setup.interpreter_search_paths)
  env = {"PATH": interpreter_search_paths, **pex_build_environment.invocation_environment_dict}

  interpreter_constraint_args = []
  for constraint in request.interpreter_constraints:
    interpreter_constraint_args.extend(["--interpreter-constraint", constraint])

  # NB: we use the hardcoded and generic bin name `python`, rather than something dynamic like
  # `sys.executable`, to ensure that the interpreter may be discovered both locally and in remote
  # execution (so long as `env` is populated with a `PATH` env var and `python` is discoverable
  # somewhere on that PATH). This is only used to run the downloaded PEX tool; it is not
  # necessarily the interpreter that PEX will use to execute the generated .pex file.
  # TODO(#7735): Set --python-setup-interpreter-search-paths differently for the host and target
  # platforms, when we introduce platforms in https://github.com/pantsbuild/pants/issues/7735.
  argv = ["python", f"./{pex_bin.executable}", "--output-file", request.output_filename]
  if request.entry_point is not None:
    argv.extend(["--entry-point", request.entry_point])
  argv.extend(interpreter_constraint_args + list(request.requirements))
  # NOTE
  # PEX outputs are platform dependent so in order to get a PEX that we can use locally, without cross-building
  # we specify that out PEX command be run on the current local platform. When we support cross-building
  # through CLI flags we can configure requests that build a PEX for out local platform that are
  # able to execute on a different platform, but for now in order to guarantee correct build we need
  # to restrict this command to execute on the same platform type that the output is intended for.
  # The correct way to interpret the keys (execution_platform_constraint, target_platform_constraint)
  # of this dictionary is "The output of this command is intended for `target_platform_constraint` iff
  # it is run on `execution_platform_constraint`".
  execute_process_request = MultiPlatformExecuteProcessRequest(
    {
      (PlatformConstraint(platform.value), PlatformConstraint(platform.value)): ExecuteProcessRequest(
        argv=tuple(argv),
        env=env,
        input_files=pex_bin.directory_digest,
        description=f"Create a requirements PEX: {', '.join(request.requirements)}",
        output_files=(request.output_filename,))
    }
  )

  result = yield Get(ExecuteProcessResult, MultiPlatformExecuteProcessRequest, execute_process_request)
  yield RequirementsPex(directory_digest=result.output_directory_digest)


def rules():
  return [
    create_requirements_pex,
    optionable_rule(PythonSetup),
    optionable_rule(PythonNativeCode),
  ]
