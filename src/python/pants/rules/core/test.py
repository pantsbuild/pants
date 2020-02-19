# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE
from pants.base.specs import FilesystemLiteralSpec, SingleAddress
from pants.build_graph.address import Address
from pants.engine.addressable import AddressesWithOrigins, AddressWithOrigin
from pants.engine.console import Console
from pants.engine.fs import Digest
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.interactive_runner import InteractiveProcessRequest, InteractiveRunner
from pants.engine.isolated_process import FallibleExecuteProcessResult
from pants.engine.legacy.graph import HydratedTargetWithOrigin
from pants.engine.legacy.structs import TargetAdaptorWithOrigin
from pants.engine.objects import union
from pants.engine.rules import UnionMembership, goal_rule, rule
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
    process_result: FallibleExecuteProcessResult,
  ) -> "TestResult":
    return TestResult(
      status=Status.SUCCESS if process_result.exit_code == 0 else Status.FAILURE,
      stdout=process_result.stdout.decode(),
      stderr=process_result.stderr.decode(),
      _python_sqlite_coverage_file=process_result.output_directory_digest,
    )


@dataclass(frozen=True)
class TestDebugRequest:
  ipr: InteractiveProcessRequest

  # Prevent this class from being detected by pytest as a test class.
  __test__ = False


@union
class TestTarget:
  """A union for registration of a testable target type.

  The union members should be subclasses of TargetAdaptorWithOrigin.
  """

  # Prevent this class from being detected by Pytest as a test class.
  __test__ = False

  @staticmethod
  def non_member_error_message(subject):
    if hasattr(subject, "address"):
      return f"{subject.address.reference()} is not a testable target."
    return None


@dataclass(frozen=True)
class AddressAndTestResult:
  address: Address
  test_result: Optional[TestResult]  # If None, target was not a test target.

  @staticmethod
  def is_testable(
    adaptor_with_origin: TargetAdaptorWithOrigin, *, union_membership: UnionMembership
  ) -> bool:
    is_test_target = union_membership.is_member(TestTarget, adaptor_with_origin)
    is_not_a_glob = isinstance(adaptor_with_origin.origin, (SingleAddress, FilesystemLiteralSpec))
    has_sources = hasattr(adaptor_with_origin.adaptor, "sources") and bool(
      adaptor_with_origin.adaptor.sources.snapshot.files
    )
    return has_sources and (is_test_target or is_not_a_glob)


@dataclass(frozen=True)
class AddressAndDebugRequest:
  address: Address
  request: TestDebugRequest


class TestOptions(GoalSubsystem):
  """Runs tests."""

  name = "test"

  required_union_implementations = (TestTarget,)

  # Prevent this class from being detected by pytest as a test class.
  __test__ = False

  @classmethod
  def register_options(cls, register) -> None:
    super().register_options(register)
    register(
      "--debug",
      type=bool,
      default=False,
      help="Run a single test target in an interactive process. This is necessary, for example, when you add "
      "breakpoints in your code.",
    )
    register(
      "--run-coverage",
      type=bool,
      default=False,
      help="Generate a coverage report for this test run.",
    )


class Test(Goal):
  subsystem_cls = TestOptions


@goal_rule
async def run_tests(
  console: Console,
  options: TestOptions,
  runner: InteractiveRunner,
  addresses_with_origins: AddressesWithOrigins,
) -> Test:
  if options.values.debug:
    address_with_origin = addresses_with_origins.expect_single()
    addr_debug_request = await Get[AddressAndDebugRequest](AddressWithOrigin, address_with_origin)
    result = runner.run_local_interactive_process(addr_debug_request.request.ipr)
    return Test(result.process_exit_code)

  results = await MultiGet(
    Get[AddressAndTestResult](AddressWithOrigin, address_with_origin)
    for address_with_origin in addresses_with_origins
  )
  did_any_fail = False
  filtered_results = [(x.address, x.test_result) for x in results if x.test_result is not None]

  for address, test_result in filtered_results:
    if test_result.status == Status.FAILURE:
      did_any_fail = True
    if test_result.stdout:
      console.write_stdout(f"{address.reference()} stdout:\n{test_result.stdout}\n")
    if test_result.stderr:
      # NB: we write to stdout, rather than to stderr, to avoid potential issues interleaving the
      # two streams.
      console.write_stdout(f"{address.reference()} stderr:\n{test_result.stderr}\n")

  console.write_stdout("\n")

  for address, test_result in filtered_results:
    console.print_stdout(f"{address.reference():80}.....{test_result.status.value:>10}")

  if did_any_fail:
    console.print_stderr(console.red("\nTests failed"))
    exit_code = PANTS_FAILED_EXIT_CODE
  else:
    exit_code = PANTS_SUCCEEDED_EXIT_CODE

  return Test(exit_code)


@rule
async def coordinator_of_tests(
  target_with_origin: HydratedTargetWithOrigin, union_membership: UnionMembership
) -> AddressAndTestResult:
  target = target_with_origin.target
  adaptor_with_origin = TargetAdaptorWithOrigin.create(
    adaptor=target.adaptor, origin=target_with_origin.origin
  )

  if not AddressAndTestResult.is_testable(adaptor_with_origin, union_membership=union_membership):
    return AddressAndTestResult(target.address, None)

  # TODO(#6004): when streaming to live TTY, rely on V2 UI for this information. When not a
  # live TTY, periodically dump heavy hitters to stderr. See
  # https://github.com/pantsbuild/pants/issues/6004#issuecomment-492699898.
  logger.info(f"Starting tests: {target.address.reference()}")
  # NB: This has the effect of "casting" a TargetAdaptorWithOrigin to a member of the TestTarget
  # union. If the adaptor is not a member of the union, the engine will fail at runtime with a
  # useful error message.
  result = await Get[TestResult](TestTarget, adaptor_with_origin)
  logger.info(
    f"Tests {'succeeded' if result.status == Status.SUCCESS else 'failed'}: "
    f"{target.address.reference()}"
  )
  return AddressAndTestResult(target.address, result)


@rule
async def coordinator_of_debug_tests(
  target_with_origin: HydratedTargetWithOrigin,
) -> AddressAndDebugRequest:
  target = target_with_origin.target
  adaptor_with_origin = TargetAdaptorWithOrigin.create(
    adaptor=target.adaptor, origin=target_with_origin.origin
  )
  logger.info(f"Starting tests in debug mode: {target.address.reference()}")
  request = await Get[TestDebugRequest](TestTarget, adaptor_with_origin)
  return AddressAndDebugRequest(target.address, request)


def rules():
  return [coordinator_of_tests, coordinator_of_debug_tests, run_tests]
