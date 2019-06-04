# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from future.utils import text_type

from pants.backend.python.subsystems.python_native_code import PexBuildEnvironment
from pants.engine.fs import Digest, Snapshot, UrlToFetch
from pants.engine.rules import rule
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.selectors import Get
from pants.util.strutil import create_path_env_var


# TODO: This is non-hermetic because the requirements will be resolved on the fly by
# pex, where it should be hermetically provided in some way.
@rule(ExecuteProcessRequest, [
])
def resolve_requirements(
  requirements,
  output_filename,
  entry_point,
  interpreter_constraints,
  python_setup,
  pex_build_environment,
):
  """Returns a PEX with the given requirements, optional entry point, and optional
  interpreter constraints."""

  # TODO: Inject versions and digests here through some option, rather than hard-coding it.
  url = 'https://github.com/pantsbuild/pex/releases/download/v1.6.6/pex'
  digest = Digest('61bb79384db0da8c844678440bd368bcbfac17bbdb865721ad3f9cb0ab29b629', 1826945)
  pex_snapshot = yield Get(Snapshot, UrlToFetch(url, digest))

  interpreter_search_paths = text_type(create_path_env_var(python_setup.interpreter_search_paths))
  env = {"PATH": interpreter_search_paths}
  # TODO(#6071): merge the two dicts via ** unpacking once we drop Py2.
  env.update(pex_build_environment.invocation_environment_dict)

  interpreter_constraint_args = []
  for constraint in sorted(interpreter_constraints):
    interpreter_constraint_args.extend(["--interpreter-constraint", text_type(constraint)])

  argv = [
    "python",
    './{}'.format(pex_snapshot.files[0]),
    '-e', entry_point,
    '-o', output_filename,
   ] + interpreter_constraint_args + [
     # Sort all user requirement strings to increase the chance of cache hits across invocations.
     # TODO(#7061): This text_type() wrapping can be removed after we drop py2!
     text_type(req) for req in sorted(requirements)
   ]

  request = ExecuteProcessRequest(
    argv=tuple(argv),
    env=env,
    input_files=pex_snapshot.directory_digest,
    description='Resolve requirements: {}'.format(", ".join(requirements)),
    output_files=(output_filename,),
  )

  yield Get(ExecuteProcessResult, ExecuteProcessRequest, request)


def rules():
  return [
    resolve_requirements,
  ]
