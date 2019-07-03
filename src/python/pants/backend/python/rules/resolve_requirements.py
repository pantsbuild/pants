# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.python_native_code import PexBuildEnvironment, PythonNativeCode
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.engine.fs import Digest, Snapshot, UrlToFetch
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.rules import optionable_rule, rule
from pants.engine.selectors import Get
from pants.util.objects import datatype, hashable_string_list, string_optional, string_type
from pants.util.strutil import create_path_env_var


class ResolveRequirementsRequest(datatype([
  ('output_filename', string_type),
  ('requirements', hashable_string_list),
  ('interpreter_constraints', hashable_string_list),
  ('entry_point', string_optional),
])):
  pass


class ResolvedRequirementsPex(datatype([('directory_digest', Digest)])):
  pass


# TODO: This is non-hermetic because the requirements will be resolved on the fly by
# pex, where it should be hermetically provided in some way.
@rule(ResolvedRequirementsPex, [ResolveRequirementsRequest, PythonSetup, PexBuildEnvironment])
def resolve_requirements(request, python_setup, pex_build_environment):
  """Returns a PEX with the given requirements, optional entry point, and optional
  interpreter constraints."""

  # TODO: Inject versions and digests here through some option, rather than hard-coding it.
  url = 'https://github.com/pantsbuild/pex/releases/download/v1.6.8/pex'
  digest = Digest('2ca320aede7e7bbcb907af54c9de832707a1df965fb5a0d560f2df29ba8a2f3d', 1866441)
  pex_snapshot = yield Get(Snapshot, UrlToFetch(url, digest))

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
  argv = ["python", "./{}".format(pex_snapshot.files[0]), "-o", request.output_filename]
  if request.entry_point is not None:
    argv.extend(["-e", request.entry_point])
  argv.extend(interpreter_constraint_args + list(request.requirements))

  request = ExecuteProcessRequest(
    argv=tuple(argv),
    env=env,
    input_files=pex_snapshot.directory_digest,
    description='Resolve requirements: {}'.format(", ".join(request.requirements)),
    output_files=(request.output_filename,),
  )

  result = yield Get(ExecuteProcessResult, ExecuteProcessRequest, request)
  yield ResolvedRequirementsPex(
    directory_digest=result.output_directory_digest,
  )


def rules():
  return [
    resolve_requirements,
    optionable_rule(PythonSetup),
    optionable_rule(PythonNativeCode),
  ]
