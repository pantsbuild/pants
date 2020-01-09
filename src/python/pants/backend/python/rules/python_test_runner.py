# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from dataclasses import dataclass
from textwrap import dedent
from typing import Optional, Set, Tuple

from pants.backend.python.rules.pex import Pex
from pants.backend.python.rules.pex_from_target_closure import CreatePexFromTargetClosure
from pants.backend.python.rules.prepare_chrooted_python_sources import ChrootedPythonSources
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.build_graph.address import Address
from pants.engine.addressable import BuildFileAddresses
from pants.engine.fs import Digest, DirectoriesToMerge, FileContent, InputFilesContent
from pants.engine.interactive_runner import InteractiveProcessRequest, InteractiveRunner
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.engine.legacy.graph import HydratedTargets, TransitiveHydratedTargets
from pants.engine.legacy.structs import PythonTestsAdaptor
from pants.engine.rules import UnionRule, rule, subsystem_rule
from pants.engine.selectors import Get
from pants.option.global_options import GlobalOptions
from pants.rules.core.strip_source_root import SourceRootStrippedSources
from pants.rules.core.test import TestDebugResult, TestOptions, TestResult, TestTarget


DEFAULT_COVERAGE_CONFIG = dedent(f"""
  [run]
  branch = True
  timid = False
  relative_files = True
  """)


def get_coveragerc_input(coveragerc_content: bytes):
  return InputFilesContent(
    [
      FileContent(
        path='.coveragerc',
        content=coveragerc_content,
        is_executable=False,
      ),
    ]
  )


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


@dataclass(frozen=True)
class TestTargetSetup:
  requirements_pex: Pex
  args: Tuple[str, ...]
  input_files_digest: Digest


def get_packages_to_cover(
  test_target: PythonTestsAdaptor,
  source_root_stripped_file_paths: Tuple[str, ...],
) -> Set[str]:
  if hasattr(test_target, 'coverage'):
    return set(test_target.coverage)
  return set(
    os.path.dirname(source_root_stripped_source_file_path).replace(os.sep, '.')
    for source_root_stripped_source_file_path in source_root_stripped_file_paths
  )


@rule
async def setup_pytest_for_target(test_target: PythonTestsAdaptor, pytest: PyTest, test_options: TestOptions) -> TestTargetSetup:
  transitive_hydrated_targets = await Get[TransitiveHydratedTargets](
    BuildFileAddresses((test_target.address,))
  )
  all_targets = transitive_hydrated_targets.closure

  resolved_requirements_pex = await Get[Pex](
    CreatePexFromTargetClosure(
      build_file_addresses=BuildFileAddresses((test_target.address,)),
      output_filename='pytest-with-requirements.pex',
      entry_point="pytest:main",
      additional_requirements=pytest.get_requirement_strings(),
      include_source_files=False
    )
  )

  # Get the file names for the test_target, adjusted for the source root. This allows us to
  # specify to Pytest which files to test and thus to avoid the test auto-discovery defined by
  # https://pytest.org/en/latest/goodpractices.html#test-discovery. In addition to a performance
  # optimization, this ensures that any transitive sources, such as a test project file named
  # test_fail.py, do not unintentionally end up being run as tests.
  source_root_stripped_test_target_sources = await Get[SourceRootStrippedSources](
    Address, test_target.address.to_address()
  )

  chrooted_sources = await Get[ChrootedPythonSources](HydratedTargets(all_targets))

  coveragerc_digest = await Get[Digest](InputFilesContent, get_coveragerc_input(DEFAULT_COVERAGE_CONFIG.encode()))

  merged_input_files: Digest = await Get[Digest](
    DirectoriesToMerge(
      directories=(
        chrooted_sources.digest,
        resolved_requirements_pex.directory_digest,
        coveragerc_digest,
      )
    ),
  )
  test_target_sources_file_names = source_root_stripped_test_target_sources.snapshot.files
  coverage_args = []
  if test_options.values.coverage:
    packages_to_cover = get_packages_to_cover(
      test_target,
      source_root_stripped_file_paths=test_target_sources_file_names,
    )
    coverage_args = [
      '--cov-report=', # To not generate any output. https://pytest-cov.readthedocs.io/en/latest/config.html
    ]
    for package in packages_to_cover:
      coverage_args.extend(['--cov', package])

  return TestTargetSetup(
    requirements_pex=resolved_requirements_pex,
    args=(*pytest.options.args, *coverage_args, *sorted(test_target_sources_file_names)),
    input_files_digest=merged_input_files
  )


@rule(name="Run pytest")
async def run_python_test(
  test_target: PythonTestsAdaptor,
  test_setup: TestTargetSetup,
  pytest: PyTest,
  python_setup: PythonSetup,
  subprocess_encoding_environment: SubprocessEncodingEnvironment,
  global_options: GlobalOptions,
) -> TestResult:
  """Runs pytest for one target."""

  timeout_seconds = calculate_timeout_seconds(
    timeouts_enabled=pytest.options.timeouts,
    target_timeout=getattr(test_target, 'timeout', None),
    timeout_default=pytest.options.timeout_default,
    timeout_maximum=pytest.options.timeout_maximum,
  )

  colors = global_options.colors
  env = {"PYTEST_ADDOPTS": f"--color={'yes' if colors else 'no'}"}

  request = test_setup.requirements_pex.create_execute_request(
    python_setup=python_setup,
    subprocess_encoding_environment=subprocess_encoding_environment,
    pex_path=f'./{test_setup.requirements_pex.output_filename}',
    pex_args=test_setup.args,
    input_files=test_setup.input_files_digest,
    output_directories=('.coverage',),
    description=f'Run Pytest for {test_target.address.reference()}',
    timeout_seconds=timeout_seconds if timeout_seconds is not None else 9999,
    env=env
  )
  result = await Get[FallibleExecuteProcessResult](ExecuteProcessRequest, request)
  return TestResult.from_fallible_execute_process_result(result)


@rule(name="Run pytest in an interactive process")
async def debug_python_test(
  test_target: PythonTestsAdaptor,
  test_setup: TestTargetSetup,
  runner: InteractiveRunner
) -> TestDebugResult:

  run_request = InteractiveProcessRequest(
    argv=(test_setup.requirements_pex.output_filename, *test_setup.args),
    run_in_workspace=False,
    input_files=test_setup.input_files_digest
  )

  result = runner.run_local_interactive_process(run_request)
  return TestDebugResult(result.process_exit_code)


def rules():
  return [
    run_python_test,
    debug_python_test,
    setup_pytest_for_target,
    UnionRule(TestTarget, PythonTestsAdaptor),
    subsystem_rule(PyTest),
    subsystem_rule(PythonSetup),
  ]
