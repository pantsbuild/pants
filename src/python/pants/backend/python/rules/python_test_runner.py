# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os.path
import sys
from builtins import str

from pants.engine.fs import Digest, MergedDirectories, Snapshot, UrlToFetch
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.engine.legacy.graph import TransitiveHydratedTarget
from pants.engine.rules import rule
from pants.engine.selectors import Get, Select
from pants.rules.core.core_test_model import Status, TestResult


# This class currently exists so that other rules could be added which turned a HydratedTarget into
# a language-specific test result, and could be installed alongside run_python_test.
# Hopefully https://github.com/pantsbuild/pants/issues/4535 should help resolve this.
class PyTestResult(TestResult):
  pass


# TODO: Support deps
# TODO: Support resources
@rule(PyTestResult, [Select(TransitiveHydratedTarget)])
def run_python_test(transitive_hydrated_target):
  target_root = transitive_hydrated_target.root

  # TODO: Inject versions and digests here through some option, rather than hard-coding it.
  pex_snapshot = yield Get(Snapshot, UrlToFetch("https://github.com/pantsbuild/pex/releases/download/v1.5.2/pex27",
                                                Digest('8053a79a5e9c2e6e9ace3999666c9df910d6289555853210c1bbbfa799c3ecda', 1757011)))

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

  output_pytest_requirements_pex_filename = 'pytest-with-requirements.pex'
  requirements_pex_argv = [
    './{}'.format(pex_snapshot.files[0].path),
    '--python', python_binary,
    '-e', 'pytest:main',
    '-o', output_pytest_requirements_pex_filename,
    # TODO: This is non-hermetic because pytest will be resolved on the fly by pex27, where it should be hermetically provided in some way.
    # We should probably also specify a specific version.
    'pytest',
    # Sort all the requirement strings to increase the chance of cache hits across invocations.
  ] + sorted(all_requirements)
  requirements_pex_request = ExecuteProcessRequest(
    argv=tuple(requirements_pex_argv),
    input_files=pex_snapshot.directory_digest,
    description='Resolve requirements for {}'.format(target_root.address.reference()),
    # TODO: This should not be necessary
    env={'PATH': os.path.dirname(python_binary)},
    output_files=(output_pytest_requirements_pex_filename,),
  )
  requirements_pex_response = yield Get(
    FallibleExecuteProcessResult, ExecuteProcessRequest, requirements_pex_request)

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

  yield PyTestResult(status=status, stdout=str(result.stdout))
  return
