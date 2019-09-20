# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Dict, Optional

from pants.backend.python.rules.create_requirements_pex import (RequirementsPex,
                                                                RequirementsPexRequest)
from pants.backend.python.rules.inject_init import InjectedInitDigest
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.build_graph.files import Files
from pants.engine.fs import Digest, DirectoriesToMerge, DirectoryWithPrefixToStrip
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.engine.legacy.graph import BuildFileAddresses, TransitiveHydratedTargets, HydratedTarget
from pants.engine.legacy.structs import PythonTestsAdaptor
from pants.engine.rules import UnionRule, optionable_rule, rule
from pants.engine.selectors import Get
from pants.rules.core.core_test_model import Status, TestResult, TestTarget
from pants.source.source_root import SourceRoot, SourceRootConfig
from pants.rules.core.strip_source_root import SourceRootStrippedSources
from pants.util.strutil import create_path_env_var, strip_prefix


@rule(TestResult, [PythonTestsAdaptor, PyTest, PythonSetup, SubprocessEncodingEnvironment])
def run_python_test(test_target, pytest, python_setup, subprocess_encoding_environment):
  """Runs pytest for one target."""

  # TODO(7726): replace this with a proper API to get the `closure` for a
  # TransitiveHydratedTarget.
  transitive_hydrated_targets = yield Get(
    TransitiveHydratedTargets, BuildFileAddresses((test_target.address,))
  )
  all_targets = transitive_hydrated_targets.closure

  interpreter_constraints = {
    constraint
    for target_adaptor in all_targets
    for constraint in python_setup.compatibility_or_constraints(
      getattr(target_adaptor, 'compatibility', None)
    )
  }

  # Produce a pex containing pytest and all transitive 3rdparty requirements.
  output_pytest_requirements_pex_filename = 'pytest-with-requirements.pex'
  all_target_requirements = []
  for t in all_targets:
    maybe_python_req_lib = t.adaptor
    # This is a python_requirement()-like target.
    if hasattr(maybe_python_req_lib, 'requirement'):
      all_target_requirements.append(str(maybe_python_req_lib.requirement))
    # This is a python_requirement_library()-like target.
    if hasattr(maybe_python_req_lib, 'requirements'):
      for py_req in maybe_python_req_lib.requirements:
        all_target_requirements.append(str(py_req.requirement))
  all_requirements = all_target_requirements + list(pytest.get_requirement_strings())
  resolved_requirements_pex = yield Get(
    RequirementsPex, RequirementsPexRequest(
      output_filename=output_pytest_requirements_pex_filename,
      requirements=tuple(sorted(all_requirements)),
      interpreter_constraints=tuple(sorted(interpreter_constraints)),
      entry_point="pytest:main",
    )
  )

  # Get the file names for the test_target, adjusted for the source root. This allows us to
  # specify to Pytest which files to test and thus to avoid the test auto-discovery defined by
  # https://pytest.org/en/latest/goodpractices.html#test-discovery. In addition to a performance
  # optimization, this ensures that any transitive sources, such as a test project file named
  # test_fail.py, do not unintentionally end up being run as tests.

  hydrated_target = HydratedTarget(address="", adaptor=test_target, dependencies=())
  source_root_stripped_test_target_sources = yield Get(
      SourceRootStrippedSources, HydratedTarget, hydrated_target
    )
  test_target_sources_file_names = sorted(source_root_stripped_test_target_sources.snapshot.files)

  source_root_stripped_sources = yield [
    Get(SourceRootStrippedSources, HydratedTarget, target_adaptor)
    for target_adaptor in all_targets
  ]

  stripped_sources_digests = [stripped_sources.snapshot.directory_digest for stripped_sources in source_root_stripped_sources]
  sources_digest = yield Get(
    Digest, DirectoriesToMerge(directories=tuple(stripped_sources_digests)),
  )

  inits_digest = yield Get(InjectedInitDigest, Digest, sources_digest)

  all_input_digests = [
    sources_digest,
    inits_digest.directory_digest,
    resolved_requirements_pex.directory_digest,
  ]
  merged_input_files = yield Get(
    Digest,
    DirectoriesToMerge,
    DirectoriesToMerge(directories=tuple(all_input_digests)),
  )

  interpreter_search_paths = create_path_env_var(python_setup.interpreter_search_paths)
  pex_exe_env = {
    'PATH': interpreter_search_paths,
    **subprocess_encoding_environment.invocation_environment_dict
  }

  # NB: we use the hardcoded and generic bin name `python`, rather than something dynamic like
  # `sys.executable`, to ensure that the interpreter may be discovered both locally and in remote
  # execution (so long as `env` is populated with a `PATH` env var and `python` is discoverable
  # somewhere on that PATH). This is only used to run the downloaded PEX tool; it is not
  # necessarily the interpreter that PEX will use to execute the generated .pex file.
  request = ExecuteProcessRequest(
    argv=(
      "python",
      f'./{output_pytest_requirements_pex_filename}',
      *test_target_sources_file_names
    ),
    env=pex_exe_env,
    input_files=merged_input_files,
    description=f'Run Pytest for {test_target.address.reference()}',
  )

  result = yield Get(FallibleExecuteProcessResult, ExecuteProcessRequest, request)
  status = Status.SUCCESS if result.exit_code == 0 else Status.FAILURE

  yield TestResult(
    status=status,
    stdout=result.stdout.decode(),
    stderr=result.stderr.decode(),
  )


def rules():
  return [
    run_python_test,
    UnionRule(TestTarget, PythonTestsAdaptor),
    optionable_rule(PyTest),
    optionable_rule(PythonSetup),
  ]
