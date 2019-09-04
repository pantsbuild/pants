# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules.download_pex_bin import DownloadedPexBin
from pants.backend.python.subsystems.python_native_code import PexBuildEnvironment, PythonNativeCode
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, Digest, DirectoriesToMerge
from pants.engine.isolated_process import (ExecuteProcessRequest, ExecuteProcessResult,
                                           MultiPlatformExecuteProcessRequest)
from pants.engine.platform import Platform, PlatformConstraint
from pants.engine.rules import optionable_rule, rule
from pants.engine.selectors import Get
from pants.util.objects import Exactly, datatype, hashable_string_list, string_optional, string_type
from pants.util.strutil import create_path_env_var


class MakePexRequest(datatype([
  ('output_filename', string_type),
  ('requirements', hashable_string_list),
  ('interpreter_constraints', hashable_string_list),
  ('entry_point', string_optional),
  ('input_files_digest', Exactly(Digest, type(None))),
  ('source_dirs', hashable_string_list),
])):

  def __new__(cls, output_filename, requirements, interpreter_constraints, entry_point,
              input_files_digest=None, source_dirs=()):
    return super().__new__(cls, output_filename, requirements, interpreter_constraints, entry_point,
                           input_files_digest=input_files_digest, source_dirs=source_dirs)


class RequirementsPex(datatype([('directory_digest', Digest)])):
  pass


# TODO: This is non-hermetic because the requirements will be resolved on the fly by
# pex, where it should be hermetically provided in some way.
@rule(RequirementsPex, [MakePexRequest, DownloadedPexBin, PythonSetup, PexBuildEnvironment, Platform])
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

  argv.extend(
    f'--sources-directory={src_dir}'
    for src_dir in request.source_dirs
  )

  sources_digest = request.input_files_digest if request.input_files_digest else EMPTY_DIRECTORY_DIGEST
  all_inputs = (pex_bin.directory_digest, sources_digest,)
  merged_digest = yield Get(Digest, DirectoriesToMerge(directories=all_inputs))

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
        input_files=merged_digest,
        description=f"Create a PEX with sources and requirements: {', '.join(request.requirements)}",
        output_files=(request.output_filename,)),
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
