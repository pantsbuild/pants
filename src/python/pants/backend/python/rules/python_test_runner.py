# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os.path
import sys
from builtins import str

from pants.backend.python.subsystems.pytest import PyTest
from pants.engine.fs import Digest, MergedDirectories, Snapshot, UrlToFetch
from pants.engine.isolated_process import (ExecuteProcessRequest, ExecuteProcessResult,
                                           FallibleExecuteProcessResult)
from pants.engine.legacy.graph import TransitiveHydratedTarget
from pants.engine.rules import optionable_rule, rule
from pants.engine.selectors import Get, Select
from pants.rules.core.core_test_model import Status, TestResult


# This class currently exists so that other rules could be added which turned a HydratedTarget into
# a language-specific test result, and could be installed alongside run_python_test.
# Hopefully https://github.com/pantsbuild/pants/issues/4535 should help resolve this.
class PyTestResult(TestResult):
  pass


# TODO: Support deps
# TODO: Support resources
@rule(PyTestResult, [Select(TransitiveHydratedTarget), Select(PyTest)])
def run_python_test(transitive_hydrated_target, pytest):
  target_root = transitive_hydrated_target.root

  # TODO: Inject versions and digests here through some option, rather than hard-coding it.
  interpreter_major, interpreter_minor = sys.version_info[0:2]
  pex_name, digest = {
    (2, 7): ("pex27", Digest('0ecbf48e3e240a413189194a9f829aec10446705c84db310affe36e23e741dbc', 1812737)),
    (3, 6): ("pex36", Digest('ba865e7ce7a840070d58b7ba24e7a67aff058435cfa34202abdd878e7b5d351d', 1812158)),
    (3, 7): ("pex37", Digest('51bf8e84d5290fe5ff43d45be78d58eaf88cf2a5e995101c8ff9e6a73a73343d', 1813189))
  }.get((interpreter_major, interpreter_minor), (None, None))
  if pex_name is None:
    raise ValueError("Current interpreter {}.{} is not supported, as there is no corresponding PEX to download.".format(interpreter_major, interpreter_minor))

  pex_snapshot = yield Get(Snapshot,
    UrlToFetch("https://github.com/pantsbuild/pex/releases/download/v1.6.1/{}".format(pex_name), digest))

  all_targets = [target_root] + [dep.root for dep in transitive_hydrated_target.dependencies]

  # Produce a pex containing pytest and all transitive 3rdparty requirements.
  all_requirements = []
  for maybe_python_req_lib in all_targets:
    # This is a python_requirement()-like target.
    if hasattr(maybe_python_req_lib.adaptor, 'requirement'):
      all_requirements.append(str(maybe_python_req_lib.requirement))
    # This is a python_requirement_library()-like target.
    if hasattr(maybe_python_req_lib.adaptor, 'requirements'):
      for py_req in maybe_python_req_lib.adaptor.requirements:
        all_requirements.append(str(py_req.requirement))

  # TODO: This should be configurable, both with interpreter constraints, and for remote execution.
  python_binary = sys.executable

  # TODO: This is non-hermetic because the requirements will be resolved on the fly by
  # pex27, where it should be hermetically provided in some way.
  output_pytest_requirements_pex_filename = 'pytest-with-requirements.pex'
  requirements_pex_argv = [
    './{}'.format(pex_snapshot.files[0].path),
    '--python', python_binary,
    '-e', 'pytest:main',
    '-o', output_pytest_requirements_pex_filename,
    # Sort all user requirement strings to increase the chance of cache hits across invocations.
  ] + list(pytest.get_requirement_strings()) + sorted(all_requirements)
  requirements_pex_request = ExecuteProcessRequest(
    argv=tuple(requirements_pex_argv),
    input_files=pex_snapshot.directory_digest,
    description='Resolve requirements for {}'.format(target_root.address.reference()),
    # TODO: This should not be necessary
    env={'PATH': os.path.dirname(python_binary)},
    output_files=(output_pytest_requirements_pex_filename,),
  )
  requirements_pex_response = yield Get(
    ExecuteProcessResult, ExecuteProcessRequest, requirements_pex_request)

  # Gather sources.
  # TODO: make TargetAdaptor return a 'sources' field with an empty snapshot instead of raising to
  # simplify the hasattr() checks here!
  all_sources_digests = []
  for maybe_source_target in all_targets:
    if hasattr(maybe_source_target.adaptor, 'sources'):
      sources_snapshot = maybe_source_target.adaptor.sources.snapshot
      all_sources_digests.append(sources_snapshot.directory_digest)

  all_input_digests = all_sources_digests + [
    requirements_pex_response.output_directory_digest,
  ]
  merged_input_files = yield Get(
    Digest,
    MergedDirectories,
    MergedDirectories(directories=tuple(all_input_digests)),
  )

  request = ExecuteProcessRequest(
    argv=('./pytest-with-requirements.pex',),
    input_files=merged_input_files,
    description='Run pytest for {}'.format(target_root.address.reference()),
    # TODO: This should not be necessary
    env={'PATH': os.path.dirname(python_binary)}
  )

  result = yield Get(FallibleExecuteProcessResult, ExecuteProcessRequest, request)
  # TODO: Do something with stderr?
  status = Status.SUCCESS if result.exit_code == 0 else Status.FAILURE

  yield PyTestResult(status=status, stdout=result.stdout.decode('utf-8'))


def rules():
  return [
      run_python_test,
      optionable_rule(PyTest),
    ]
