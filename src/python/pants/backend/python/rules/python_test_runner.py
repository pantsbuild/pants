# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import sys
from builtins import str

from future.utils import text_type

from pants.backend.python.subsystems.pytest import PyTest
from pants.engine.fs import Digest, MergedDirectories, PrefixStrippedDirectory, Snapshot, UrlToFetch
from pants.engine.isolated_process import (ExecuteProcessRequest, ExecuteProcessResult,
                                           FallibleExecuteProcessResult)
from pants.engine.legacy.graph import TransitiveHydratedTarget
from pants.engine.rules import optionable_rule, rule
from pants.engine.selectors import Get
from pants.rules.core.core_test_model import Status, TestResult
from pants.source.source_root import SourceRootConfig


# This class currently exists so that other rules could be added which turned a HydratedTarget into
# a language-specific test result, and could be installed alongside run_python_test.
# Hopefully https://github.com/pantsbuild/pants/issues/4535 should help resolve this.
class PyTestResult(TestResult):
  pass


# TODO: Support deps
# TODO: Support resources
@rule(PyTestResult, [TransitiveHydratedTarget, PyTest, SourceRootConfig])
def run_python_test(transitive_hydrated_target, pytest, source_root_config):
  target_root = transitive_hydrated_target.root

  # TODO: Inject versions and digests here through some option, rather than hard-coding it.
  url = 'https://github.com/pantsbuild/pex/releases/download/v1.6.6/pex'
  digest = Digest('61bb79384db0da8c844678440bd368bcbfac17bbdb865721ad3f9cb0ab29b629', 1826945)
  pex_snapshot = yield Get(Snapshot, UrlToFetch(url, digest))

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
  # TODO(#7061): This str() can be removed after we drop py2!
  python_binary = text_type(sys.executable)

  # TODO: This is non-hermetic because the requirements will be resolved on the fly by
  # pex27, where it should be hermetically provided in some way.
  output_pytest_requirements_pex_filename = 'pytest-with-requirements.pex'
  requirements_pex_argv = [
    python_binary,
    './{}'.format(pex_snapshot.files[0]),
    # TODO(#7061): This text_type() can be removed after we drop py2!
    '--python', text_type(python_binary),
    '-e', 'pytest:main',
    '-o', output_pytest_requirements_pex_filename,
    # Sort all user requirement strings to increase the chance of cache hits across invocations.
  ] + [
    # TODO(#7061): This text_type() wrapping can be removed after we drop py2!
    text_type(req)
    for req in sorted(
        list(pytest.get_requirement_strings())
        + list(all_requirements))
  ]
  requirements_pex_request = ExecuteProcessRequest(
    argv=tuple(requirements_pex_argv),
    input_files=pex_snapshot.directory_digest,
    description='Resolve requirements for {}'.format(target_root.address.reference()),
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

  source_roots = source_root_config.get_source_roots()
  all_sources_digests_adjusted_for_source_root = yield [
    # TODO: how to go from digest to target.adaptor.address...
    Get(Digest, PrefixStrippedDirectory(digest, "testprojects/tests/python"))
    for digest in all_sources_digests
  ]

  sources_digest = yield Get(
    Digest,
    MergedDirectories,
    MergedDirectories(directories=tuple(all_sources_digests_adjusted_for_source_root)),
  )

  # Take a set of source file names, return a set of __init__.py
  # Maybe use a snapshot.files field? Can convert a digest to snapshot.
  # Make the algorithm Stu linked to static, then link to it here.
  touch_init_request = ExecuteProcessRequest(
    argv=("touch", "pants/__init__.py"),
    output_files=("pants/__init__.py",),
    description="Create __init__.py",
    input_files=sources_digest,
    env={"PATH": os.environ["PATH"]}
  )

  touch_init_result = yield Get(ExecuteProcessResult, ExecuteProcessRequest, touch_init_request)

  all_input_digests = [
    sources_digest,
    requirements_pex_response.output_directory_digest,
    touch_init_result.output_directory_digest
  ]
  merged_input_files = yield Get(
    Digest,
    MergedDirectories,
    MergedDirectories(directories=tuple(all_input_digests)),
  )

  request = ExecuteProcessRequest(
    argv=(python_binary, './{}'.format(output_pytest_requirements_pex_filename)),
    input_files=merged_input_files,
    description='Run pytest for {}'.format(target_root.address.reference()),
  )

  result = yield Get(FallibleExecuteProcessResult, ExecuteProcessRequest, request)
  status = Status.SUCCESS if result.exit_code == 0 else Status.FAILURE

  yield PyTestResult(
    status=status,
    stdout=result.stdout.decode('utf-8'),
    stderr=result.stderr.decode('utf-8'),
  )


def rules():
  return [
      run_python_test,
      optionable_rule(PyTest),
      optionable_rule(SourceRootConfig),
    ]
