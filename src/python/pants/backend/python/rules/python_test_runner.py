# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List

from pants.backend.python.rules.create_requirements_pex import (RequirementsPex,
                                                                RequirementsPexRequest)
from pants.backend.python.rules.create_sources_pex import SourcesPex, SourcesPexRequest
from pants.backend.python.rules.inject_init import InjectedInitDigest
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.engine.fs import Digest, DirectoriesToMerge, Snapshot, EMPTY_DIRECTORY_DIGEST
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult, FallibleExecuteProcessResult
from pants.engine.legacy.graph import BuildFileAddresses, TransitiveHydratedTargets
from pants.engine.legacy.structs import PythonTestsAdaptor
from pants.engine.rules import UnionRule, optionable_rule, rule
from pants.engine.selectors import Get
from pants.rules.core.core_test_model import Status, TestResult, TestTarget
from pants.util.strutil import create_path_env_var


@rule(TestResult, [PythonTestsAdaptor, PyTest, PythonSetup, SubprocessEncodingEnvironment])
def run_python_test(test_target, pytest, python_setup, subprocess_encoding_environment):
  """Runs pytest for one target."""

  # TODO(7726): replace this with a proper API to get the `closure` for a
  # TransitiveHydratedTarget.
  transitive_hydrated_targets = yield Get(
    TransitiveHydratedTargets, BuildFileAddresses((test_target.address,))
  )
  all_targets = [t.adaptor for t in transitive_hydrated_targets.closure]

  interpreter_constraints = {
    constraint
    for target_adaptor in all_targets
    for constraint in python_setup.compatibility_or_constraints(
      getattr(target_adaptor, 'compatibility', None)
    )
  }

  # Build a PEX containing Pytest and all transitive 3rdparty requirements.
  requirements_pex_filename = 'pytest-with-requirements.pex'
  all_target_requirements = []
  for maybe_python_req_lib in all_targets:
    # This is a python_requirement()-like target.
    if hasattr(maybe_python_req_lib, 'requirement'):
      all_target_requirements.append(str(maybe_python_req_lib.requirement))
    # This is a python_requirement_library()-like target.
    if hasattr(maybe_python_req_lib, 'requirements'):
      for py_req in maybe_python_req_lib.requirements:
        all_target_requirements.append(str(py_req.requirement))
  all_requirements = all_target_requirements + list(pytest.get_requirement_strings())
  requirements_pex = yield Get(
    RequirementsPex, RequirementsPexRequest(
      output_filename=requirements_pex_filename,
      requirements=tuple(sorted(all_requirements)),
      interpreter_constraints=tuple(sorted(interpreter_constraints)),
      entry_point="pytest:main",
    )
  )

  interpreter_search_paths = create_path_env_var(python_setup.interpreter_search_paths)

  # Build a PEX containing all source and resource files, including missing __init__.py files.
  sources_digest_list: List[Digest] = [
    maybe_source_target.sources.snapshot.directory_digest
    for maybe_source_target in all_targets
    if hasattr(maybe_source_target, 'sources')
  ]
  sources_digest = yield Get(Digest, DirectoriesToMerge(directories=tuple(sources_digest_list)))
  inits_digest = yield Get(InjectedInitDigest, Digest, sources_digest)
  sources_and_init_snapshot = yield Get(
    Snapshot, DirectoriesToMerge(directories=(sources_digest, inits_digest.directory_digest))
  )
  sources_pex_filename = "sources.pex"
  sources_pex = yield Get(
    SourcesPex, SourcesPexRequest(
      output_filename=sources_pex_filename, sources_snapshot=sources_and_init_snapshot)
  )

  # NB: We create a basic pytest.ini config to instruct how to discover tests. Because we do not
  # supply any args to the Pytest ExecuteProcessRequest, this config is necessary to get test
  # discovery working properly. See
  # https://docs.pytest.org/en/latest/goodpractices.html#conventions-for-python-test-discovery.
  pytest_config_content = f"[testpaths]\\ntestpaths = {' '.join(sources_pex.source_roots)}"
  pytest_config_result = yield Get(ExecuteProcessResult, ExecuteProcessRequest(
    argv=("python3", "-c", f"""'from pathlib import Path; Path("pytest.ini").write_text("{pytest_config_content}")'""",),
    env={"PATH": interpreter_search_paths},
    input_files=EMPTY_DIRECTORY_DIGEST,
    description="Create pytest.ini."
  ))

  merged_input_files = yield Get(
    Digest, DirectoriesToMerge(
      directories=(
        requirements_pex.directory_digest,
        sources_pex.directory_digest,
        pytest_config_result.output_directory_digest,
      )
    ),
  )

  pex_exe_env = {
    'PATH': interpreter_search_paths,
    # This merges the source pex into the requirements pex at runtime.
    'PEX_PATH': f"./{sources_pex_filename}",
    **subprocess_encoding_environment.invocation_environment_dict,
  }

  # NB: we use the hardcoded and generic bin name `python`, rather than something dynamic like
  # `sys.executable`, to ensure that the interpreter may be discovered both locally and in remote
  # execution (so long as `env` is populated with a `PATH` env var and `python` is discoverable
  # somewhere on that PATH). This is only used to run the downloaded PEX tool; it is not
  # necessarily the interpreter that PEX will use to execute the generated .pex file.
  request = ExecuteProcessRequest(
    argv=("python", f'./{requirements_pex_filename}'),
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
