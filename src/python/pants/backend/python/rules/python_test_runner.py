# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import sys
from builtins import str

from future.utils import text_type

from pants.backend.python.subsystems.pex_build_util import identify_missing_init_files
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.engine.fs import (Digest, DirectoryWithPrefixToStrip, FilesContent, MergedDirectories,
                             Snapshot, UrlToFetch)
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
    constraints_args.extend(["--interpreter-constraint", constraint])
  return constraints_args


def resolve_all_transitive_hydrated_targets(initial_transitive_hydrated_target):
  all_targets = set()
  def recursively_add_transitive_deps(transitive_hydrated_target):
    all_targets.add(transitive_hydrated_target.root)
    for dep in transitive_hydrated_target.dependencies:
      recursively_add_transitive_deps(dep)

  recursively_add_transitive_deps(initial_transitive_hydrated_target)
  return all_targets


# TODO: Support deps
# TODO: Support resources
# TODO(7697): Use a dedicated rule for removing the source root prefix, so that this rule
# does not have to depend on SourceRootConfig.
@rule(PyTestResult, [TransitiveHydratedTarget, PyTest, PythonSetup, SourceRootConfig])
def run_python_test(transitive_hydrated_target, pytest, python_setup, source_root_config):
  target_root = transitive_hydrated_target.root

  # TODO: Inject versions and digests here through some option, rather than hard-coding it.
  url = 'https://github.com/pantsbuild/pex/releases/download/v1.6.6/pex'
  digest = Digest('61bb79384db0da8c844678440bd368bcbfac17bbdb865721ad3f9cb0ab29b629', 1826945)
  pex_snapshot = yield Get(Snapshot, UrlToFetch(url, digest))

  all_targets = resolve_all_transitive_hydrated_targets(transitive_hydrated_target)


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

  # TODO(#7061): This str() can be removed after we drop py2!
  python_binary = text_type(sys.executable)
  interpreter_constraint_args = parse_interpreter_constraints(
    python_setup, python_target_adaptors=[target.adaptor for target in all_targets]
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
    text_type(req)
    # Sort all user requirement strings to increase the chance of cache hits across invocations.
    for req in sorted(
        list(pytest.get_requirement_strings())
        + list(all_requirements))
  ]
  requirements_pex_request = ExecuteProcessRequest(
    argv=tuple(requirements_pex_argv),
    env={'PATH': os.pathsep.join(python_setup.interpreter_search_paths)},
    input_files=pex_snapshot.directory_digest,
    description='Resolve requirements for {}'.format(target_root.address.reference()),
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
    if hasattr(maybe_source_target.adaptor, 'sources'):
      tgt_snapshot = maybe_source_target.adaptor.sources.snapshot
      tgt_source_root = source_roots.find_by_path(maybe_source_target.adaptor.address.spec_path)
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
    Digest, MergedDirectories(directories=tuple(all_sources_digests)),
  )

  # TODO(7716): add a builtin rule to go from MergedDirectories->Snapshot or Digest->Snapshot.
  # TODO(7715): generalize the injection of __init__.py files.
  # TODO(7718): add a builtin rule for FilesContent->Snapshot.
  file_contents = yield Get(FilesContent, Digest, sources_digest)
  file_paths = [fc.path for fc in file_contents]
  injected_inits = tuple(sorted(identify_missing_init_files(file_paths)))
  if injected_inits:
    touch_init_request = ExecuteProcessRequest(
      argv=("/usr/bin/touch",) + injected_inits,
      output_files=injected_inits,
      description="Inject empty __init__.py into all packages without one already.",
      input_files=sources_digest,
    )
    touch_init_result = yield Get(ExecuteProcessResult, ExecuteProcessRequest, touch_init_request)

  all_input_digests = [sources_digest, requirements_pex_response.output_directory_digest]
  if injected_inits:
    all_input_digests.append(touch_init_result.output_directory_digest)

  merged_input_files = yield Get(
    Digest,
    MergedDirectories,
    MergedDirectories(directories=tuple(all_input_digests)),
  )

  request = ExecuteProcessRequest(
    argv=(python_binary, './{}'.format(output_pytest_requirements_pex_filename)),
    env={'PATH': os.pathsep.join(python_setup.interpreter_search_paths)},
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
      optionable_rule(PythonSetup),
      optionable_rule(SourceRootConfig),
    ]
