# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import sys
from builtins import str

from future.utils import text_type

from pants.backend.python.rules.inject_init import InjectedInitDigest
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.engine.fs import (Digest, DirectoriesToMerge, DirectoryWithPrefixToStrip, Snapshot,
                             UrlToFetch)
from pants.engine.isolated_process import (ExecuteProcessRequest, ExecuteProcessResult,
                                           FallibleExecuteProcessResult)
from pants.engine.legacy.graph import BuildFileAddresses, TransitiveHydratedTargets
from pants.engine.legacy.structs import PythonTestsAdaptor
from pants.engine.rules import UnionRule, optionable_rule, rule
from pants.engine.selectors import Get
from pants.rules.core.core_test_model import Status, TestResult, TestTarget
from pants.source.source_root import SourceRootConfig


def parse_interpreter_constraints(python_setup, python_target_adaptors):
  constraints = {
    constraint
    for target_adaptor in python_target_adaptors
    for constraint in python_setup.compatibility_or_constraints(
      getattr(target_adaptor, 'compatibility', None)
    )
  }
  constraints_args = []
  for constraint in sorted(constraints):
    constraints_args.extend(["--interpreter-constraint", text_type(constraint)])
  return constraints_args


# TODO: Support resources
# TODO(7697): Use a dedicated rule for removing the source root prefix, so that this rule
# does not have to depend on SourceRootConfig.
@rule(TestResult, [PythonTestsAdaptor, PyTest, PythonSetup, SourceRootConfig])
def run_python_test(test_target, pytest, python_setup, source_root_config):
  """Runs pytest for one target."""

  # TODO: Inject versions and digests here through some option, rather than hard-coding it.
  url = 'https://github.com/pantsbuild/pex/releases/download/v1.6.6/pex'
  digest = Digest('61bb79384db0da8c844678440bd368bcbfac17bbdb865721ad3f9cb0ab29b629', 1826945)
  pex_snapshot = yield Get(Snapshot, UrlToFetch(url, digest))

  # TODO(7726): replace this with a proper API to get the `closure` for a
  # TransitiveHydratedTarget.
  transitive_hydrated_targets = yield Get(
    TransitiveHydratedTargets, BuildFileAddresses((test_target.address,))
  )
  all_targets = [t.adaptor for t in transitive_hydrated_targets.closure]

  # Produce a pex containing pytest and all transitive 3rdparty requirements.
  all_target_requirements = []
  for maybe_python_req_lib in all_targets:
    # This is a python_requirement()-like target.
    if hasattr(maybe_python_req_lib, 'requirement'):
      all_target_requirements.append(str(maybe_python_req_lib.requirement))
    # This is a python_requirement_library()-like target.
    if hasattr(maybe_python_req_lib, 'requirements'):
      for py_req in maybe_python_req_lib.requirements:
        all_target_requirements.append(str(py_req.requirement))

  # Sort all user requirement strings to increase the chance of cache hits across invocations.
  all_requirements = sorted(all_target_requirements + list(pytest.get_requirement_strings()))

  # TODO(#7061): This str() can be removed after we drop py2!
  python_binary = text_type(sys.executable)
  interpreter_constraint_args = parse_interpreter_constraints(
    python_setup, python_target_adaptors=all_targets
  )

  # TODO: This is non-hermetic because the requirements will be resolved on the fly by
  # pex27, where it should be hermetically provided in some way.
  output_pytest_requirements_pex_filename = 'pytest-with-requirements.pex'
  requirements_pex_argv = [
    python_binary,
    './{}'.format(pex_snapshot.files[0]),
    '-e', 'pytest:main',
    '-o', output_pytest_requirements_pex_filename,
  ] + interpreter_constraint_args + [
    # TODO(#7061): This text_type() wrapping can be removed after we drop py2!
    text_type(req) for req in all_requirements
  ]
  requirements_pex_request = ExecuteProcessRequest(
    argv=tuple(requirements_pex_argv),
    env={'PATH': text_type(os.pathsep.join(python_setup.interpreter_search_paths))},
    input_files=pex_snapshot.directory_digest,
    description='Resolve requirements: {}'.format(", ".join(all_requirements)),
    output_files=(output_pytest_requirements_pex_filename,),
  )
  requirements_pex_response = yield Get(
    ExecuteProcessResult, ExecuteProcessRequest, requirements_pex_request)

  source_roots = source_root_config.get_source_roots()

  # Gather sources and adjust for the source root.
  # TODO: make TargetAdaptor return a 'sources' field with an empty snapshot instead of raising to
  # simplify the hasattr() checks here!
  # TODO(7714): restore the full source name for the stdout of the Pytest run.
  sources_snapshots_and_source_roots = []
  for maybe_source_target in all_targets:
    if hasattr(maybe_source_target, 'sources'):
      tgt_snapshot = maybe_source_target.sources.snapshot
      tgt_source_root = source_roots.find_by_path(maybe_source_target.address.spec_path)
      sources_snapshots_and_source_roots.append((tgt_snapshot, tgt_source_root))
  all_sources_digests = yield [
    Get(
      Digest,
      DirectoryWithPrefixToStrip(
        directory_digest=snapshot.directory_digest,
        prefix=source_root.path
      )
    )
    for snapshot, source_root
    in sources_snapshots_and_source_roots
  ]

  sources_digest = yield Get(
    Digest, DirectoriesToMerge(directories=tuple(all_sources_digests)),
  )

  inits_digest = yield Get(InjectedInitDigest, Digest, sources_digest)

  all_input_digests = [
    sources_digest,
    inits_digest.directory_digest,
    requirements_pex_response.output_directory_digest,
  ]
  merged_input_files = yield Get(
    Digest,
    DirectoriesToMerge,
    DirectoriesToMerge(directories=tuple(all_input_digests)),
  )

  request = ExecuteProcessRequest(
    argv=(python_binary, './{}'.format(output_pytest_requirements_pex_filename)),
    env={'PATH': text_type(os.pathsep.join(python_setup.interpreter_search_paths))},
    input_files=merged_input_files,
    description='Run pytest for {}'.format(test_target.address.reference()),
  )

  result = yield Get(FallibleExecuteProcessResult, ExecuteProcessRequest, request)
  status = Status.SUCCESS if result.exit_code == 0 else Status.FAILURE

  yield TestResult(
    status=status,
    stdout=result.stdout.decode('utf-8'),
    stderr=result.stderr.decode('utf-8'),
  )


def rules():
  return [
      run_python_test,
      UnionRule(TestTarget, PythonTestsAdaptor),
      optionable_rule(PyTest),
      optionable_rule(PythonSetup),
      optionable_rule(SourceRootConfig),
    ]
