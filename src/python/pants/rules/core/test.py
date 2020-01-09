# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE
from pants.base.specs import AddressSpecs, SingleAddress
from pants.build_graph.address import Address, BuildFileAddress
from pants.engine.addressable import BuildFileAddresses
from pants.engine.build_files import AddressProvenanceMap
from pants.engine.console import Console
from pants.engine.fs import Digest
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.isolated_process import FallibleExecuteProcessResult
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.objects import union
from pants.engine.rules import UnionMembership, console_rule, rule
from pants.engine.selectors import Get, MultiGet


# TODO(#6004): use proper Logging singleton, rather than static logger.
logger = logging.getLogger(__name__)


class Status(Enum):
  SUCCESS = "SUCCESS"
  FAILURE = "FAILURE"


@dataclass(frozen=True)
class TestResult:
  status: Status
  stdout: str
  stderr: str
  # TODO: We need a more generic way to handle coverage output across languages.
  # See #8915 for proposed improvements.
  _python_sqlite_coverage_file: Optional[Digest] = None

  # Prevent this class from being detected by pytest as a test class.
  __test__ = False

  @staticmethod
  def from_fallible_execute_process_result(
    process_result: FallibleExecuteProcessResult
  ) -> "TestResult":
    return TestResult(
      status=Status.SUCCESS if process_result.exit_code == 0 else Status.FAILURE,
      stdout=process_result.stdout.decode(),
      stderr=process_result.stderr.decode(),
      _python_sqlite_coverage_file=process_result.output_directory_digest,
    )


@dataclass(frozen=True)
class TestDebugResult:
  exit_code: int


@union
class TestTarget:
  """A union for registration of a testable target type."""

  # Prevent this class from being detected by pytest as a test class.
  __test__ = False

  @staticmethod
  def non_member_error_message(subject):
    if hasattr(subject, 'address'):
      return f'{subject.address.reference()} is not a testable target.'
    return None


class TestOptions(GoalSubsystem):
  """Runs tests."""
  name = "test"

  @classmethod
  def register_options(cls, register) -> None:
    super().register_options(register)
    register('--debug', type=bool, default=False,
             help='Run a single test target in an interactive process. This is '
                  'necessary, for example, when you add breakpoints in your code.')


class Test(Goal):
  subsystem_cls = TestOptions


@dataclass(frozen=True)
class AddressAndTestResult:
  address: BuildFileAddress
  test_result: Optional[TestResult]  # If None, target was not a test target.

  @staticmethod
  def is_testable(
    target: HydratedTarget,
    *,
    union_membership: UnionMembership,
    provenance_map: AddressProvenanceMap
  ) -> bool:
    is_valid_target_type = (
      provenance_map.is_single_address(target.address)
      or union_membership.is_member(TestTarget, target.adaptor)
    )
    has_sources = hasattr(target.adaptor, "sources") and target.adaptor.sources.snapshot.files
    return is_valid_target_type and has_sources


@dataclass(frozen=True)
class AddressAndDebugResult:
  address: BuildFileAddress
  test_result: TestDebugResult


@console_rule
async def run_tests(console: Console, options: TestOptions, addresses: BuildFileAddresses) -> Test:
  if options.values.debug:
    dependencies = tuple(SingleAddress(addr.spec_path, addr.target_name) for addr in addresses)
    address = await Get[BuildFileAddress](AddressSpecs(dependencies=dependencies))
    result = await Get[AddressAndDebugResult](Address, address.to_address())
    return Test(result.test_result.exit_code)
  results = await MultiGet(Get[AddressAndTestResult](Address, addr.to_address()) for addr in addresses)
  did_any_fail = False
  filtered_results = [(x.address, x.test_result) for x in results if x.test_result is not None]

  for address, test_result in filtered_results:
    if test_result.status == Status.FAILURE:
      did_any_fail = True
    if test_result.stdout:
      console.write_stdout(
        "{} stdout:\n{}\n".format(
          address.reference(),
          (console.red(test_result.stdout) if test_result.status == Status.FAILURE
           else test_result.stdout)
        )
      )
    if test_result.stderr:
      # NB: we write to stdout, rather than to stderr, to avoid potential issues interleaving the
      # two streams.
      console.write_stdout(
        "{} stderr:\n{}\n".format(
          address.reference(),
          (console.red(test_result.stderr) if test_result.status == Status.FAILURE
           else test_result.stderr)
        )
      )

  console.write_stdout("\n")

  for address, test_result in filtered_results:
    console.print_stdout('{0:80}.....{1:>10}'.format(
      address.reference(), test_result.status.value))

  if did_any_fail:
    console.print_stderr(console.red('Tests failed'))
    exit_code = PANTS_FAILED_EXIT_CODE
  else:
    exit_code = PANTS_SUCCEEDED_EXIT_CODE

  return Test(exit_code)


@rule
async def coordinator_of_tests(
  target: HydratedTarget,
  union_membership: UnionMembership,
  provenance_map: AddressProvenanceMap
) -> AddressAndTestResult:

  if not AddressAndTestResult.is_testable(
    target, union_membership=union_membership, provenance_map=provenance_map
  ):
    return AddressAndTestResult(target.address, None)

  # TODO(#6004): when streaming to live TTY, rely on V2 UI for this information. When not a
  # live TTY, periodically dump heavy hitters to stderr. See
  # https://github.com/pantsbuild/pants/issues/6004#issuecomment-492699898.
  logger.info("Starting tests: {}".format(target.address.reference()))
  # NB: This has the effect of "casting" a TargetAdaptor to a member of the TestTarget union.
  # The adaptor will always be a member because of the union membership check above, but if
  # it were not it would fail at runtime with a useful error message.
  result = await Get[TestResult](TestTarget, target.adaptor)
  logger.info("Tests {}: {}".format(
    "succeeded" if result.status == Status.SUCCESS else "failed",
    target.address.reference(),
  ))
  return AddressAndTestResult(target.address, result)


@rule
async def coordinator_of_debug_tests(target: HydratedTarget) -> AddressAndDebugResult:
  logger.info(f"Starting tests in debug mode: {target.address.reference()}")
  result = await Get[TestDebugResult](TestTarget, target.adaptor)
  return AddressAndDebugResult(target.address, result)


def rules():
  return [
      coordinator_of_tests,
      coordinator_of_debug_tests,
      run_tests,
    ]
