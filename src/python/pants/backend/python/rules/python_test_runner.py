# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Optional

from pants.backend.python.rules.inject_init import InjectedInitDigest
from pants.backend.python.rules.pex import (
  CreatePex,
  Pex,
  PexInterpreterConstraints,
  PexRequirements,
)
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.build_graph.address import Address
from pants.engine.fs import Digest, DirectoriesToMerge
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.engine.legacy.graph import BuildFileAddresses, HydratedTarget, TransitiveHydratedTargets
from pants.engine.legacy.structs import PythonTestsAdaptor
from pants.engine.rules import UnionRule, optionable_rule, rule
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.core_test_model import TestResult, TestTarget
from pants.rules.core.strip_source_root import SourceRootStrippedSources


def calculate_timeout_seconds(
  *,
  timeouts_enabled: bool,
  target_timeout: Optional[int],
  timeout_default: Optional[int],
  timeout_maximum: Optional[int],
) -> Optional[int]:
  """Calculate the timeout for a test target.

  If a target has no timeout configured its timeout will be set to the default timeout.
  """
  if not timeouts_enabled:
    return None
  if target_timeout is None:
    if timeout_default is None:
      return None
    target_timeout = timeout_default
  if timeout_maximum is not None:
    return min(target_timeout, timeout_maximum)
  return target_timeout


@rule(name="Run pytest")
async def run_python_test(
  test_target: PythonTestsAdaptor,
  pytest: PyTest,
  python_setup: PythonSetup,
  subprocess_encoding_environment: SubprocessEncodingEnvironment
) -> TestResult:
  """Runs pytest for one target."""

  # TODO(7726): replace this with a proper API to get the `closure` for a
  # TransitiveHydratedTarget.
  transitive_hydrated_targets = await Get(
    TransitiveHydratedTargets, BuildFileAddresses((test_target.address,))
  )
  all_targets = transitive_hydrated_targets.closure
  all_target_adaptors = tuple(t.adaptor for t in all_targets)

  interpreter_constraints = PexInterpreterConstraints.create_from_adaptors(
    adaptors=tuple(all_target_adaptors),
    python_setup=python_setup
  )

  output_pytest_requirements_pex_filename = 'pytest-with-requirements.pex'
  requirements = PexRequirements.create_from_adaptors(
    adaptors=all_target_adaptors,
    additional_requirements=pytest.get_requirement_strings()
  )
  resolved_requirements_pex = await Get(
    Pex, CreatePex(
      output_filename=output_pytest_requirements_pex_filename,
      requirements=requirements,
      interpreter_constraints=interpreter_constraints,
      entry_point="pytest:main",
    )
  )

  # Get the file names for the test_target, adjusted for the source root. This allows us to
  # specify to Pytest which files to test and thus to avoid the test auto-discovery defined by
  # https://pytest.org/en/latest/goodpractices.html#test-discovery. In addition to a performance
  # optimization, this ensures that any transitive sources, such as a test project file named
  # test_fail.py, do not unintentionally end up being run as tests.
  source_root_stripped_test_target_sources = await Get(
    SourceRootStrippedSources, Address, test_target.address.to_address()
  )

  source_root_stripped_sources = await MultiGet(
    Get(SourceRootStrippedSources, HydratedTarget, hydrated_target)
    for hydrated_target in all_targets
  )

  stripped_sources_digests = tuple(
    stripped_sources.snapshot.directory_digest for stripped_sources in source_root_stripped_sources
  )
  sources_digest = await Get(Digest, DirectoriesToMerge(directories=stripped_sources_digests))

  inits_digest = await Get(InjectedInitDigest, Digest, sources_digest)

  merged_input_files = await Get(
    Digest,
    DirectoriesToMerge(
      directories=(
        sources_digest,
        inits_digest.directory_digest,
        resolved_requirements_pex.directory_digest,
      )
    ),
  )

  test_target_sources_file_names = sorted(source_root_stripped_test_target_sources.snapshot.files)
  timeout_seconds = calculate_timeout_seconds(
    timeouts_enabled=pytest.options.timeouts,
    target_timeout=getattr(test_target, 'timeout', None),
    timeout_default=pytest.options.timeout_default,
    timeout_maximum=pytest.options.timeout_maximum,
  )
  request = resolved_requirements_pex.create_execute_request(
    python_setup=python_setup,
    subprocess_encoding_environment=subprocess_encoding_environment,
    pex_path=f'./{output_pytest_requirements_pex_filename}',
    pex_args=(*pytest.get_args(), *test_target_sources_file_names),
    input_files=merged_input_files,
    description=f'Run Pytest for {test_target.address.reference()}',
    timeout_seconds=timeout_seconds if timeout_seconds is not None else 9999
  )
  result = await Get(FallibleExecuteProcessResult, ExecuteProcessRequest, request)
  return TestResult.from_fallible_execute_process_result(result)


def rules():
  return [
    run_python_test,
    UnionRule(TestTarget, PythonTestsAdaptor),
    optionable_rule(PyTest),
    optionable_rule(PythonSetup),
  ]
