# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from future.utils import text_type

from pants.backend.python.subsystems.python_native_code import PexBuildEnvironment
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.engine.fs import Digest, Snapshot, UrlToFetch
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.rules import optionable_rule, rule
from pants.engine.selectors import Get
from pants.util.objects import datatype, hashable_string_list, string_optional, string_type
from pants.util.strutil import create_path_env_var


class ResolveRequirementsRequest(datatype([
  ('requirements', hashable_string_list),
  ('output_filename', string_type),
  ('entry_point', string_optional),
  ('interpreter_constraints', hashable_string_list),
])):
  pass


class ResolvedRequirementsPex(datatype([
  ('directory_digest', Digest),
  ('requirements', hashable_string_list)
])):
  pass


# TODO: This is non-hermetic because the requirements will be resolved on the fly by
# pex, where it should be hermetically provided in some way.
@rule(ResolvedRequirementsPex, [ResolveRequirementsRequest, PythonSetup, PexBuildEnvironment])
def resolve_requirements(request, python_setup, pex_build_environment):
  """Returns a PEX with the given requirements, optional entry point, and optional
  interpreter constraints."""

  # Sort all user requirement strings to increase the chance of cache hits across invocations.
  # TODO(#7061): This text_type() wrapping can be removed after we drop py2!
  sorted_requirements = list(sorted(text_type(req) for req in request.requirements))

  # TODO: Inject versions and digests here through some option, rather than hard-coding it.
  url = 'https://github.com/pantsbuild/pex/releases/download/v1.6.6/pex'
  digest = Digest('61bb79384db0da8c844678440bd368bcbfac17bbdb865721ad3f9cb0ab29b629', 1826945)
  pex_snapshot = yield Get(Snapshot, UrlToFetch(url, digest))

  interpreter_search_paths = text_type(create_path_env_var(python_setup.interpreter_search_paths))
  env = {"PATH": interpreter_search_paths}
  # TODO(#6071): merge the two dicts via ** unpacking once we drop Py2.
  env.update(pex_build_environment.invocation_environment_dict)

  interpreter_constraint_args = []
  for constraint in sorted(request.interpreter_constraints):
    interpreter_constraint_args.extend(["--interpreter-constraint", text_type(constraint)])

  # NB: we use the hardcoded and generic bin name `python`, rather than something dynamic like
  # `sys.executable`, to ensure that the python_binary may be discovered both locally and in remote
  # execution. This is only used to run the downloaded PEX tool; it is not necessarily the
  # interpreter that PEX will use to execute the generated .pex file.
  argv = ["python", "./{}".format(pex_snapshot.files[0]), "-o", request.output_filename]
  if request.entry_point is not None:
    argv.extend(["-e", request.entry_point])
  argv.extend(interpreter_constraint_args)
  argv.extend(sorted_requirements)

  request = ExecuteProcessRequest(
    argv=tuple(argv),
    env=env,
    input_files=pex_snapshot.directory_digest,
    description='Resolve requirements: {}'.format(", ".join(sorted_requirements)),
    output_files=(request.output_filename,),
  )

  result = yield Get(ExecuteProcessResult, ExecuteProcessRequest, request)
  yield ResolvedRequirementsPex(
    directory_digest=result.output_directory_digest,
    requirements=tuple(sorted_requirements),
  )


def rules():
  return [
    resolve_requirements,
    optionable_rule(PythonSetup),
  ]
