# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath
from typing import Optional, Type

from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE
from pants.base.specs import FilesystemLiteralSpec, SingleAddress
from pants.build_graph.address import Address
from pants.engine.addressable import AddressesWithOrigins, AddressWithOrigin
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoryToMaterialize, Workspace
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
    coverage_data: Optional["CoverageData"] = None

    # Prevent this class from being detected by pytest as a test class.
    __test__ = False

    @staticmethod
    def from_fallible_execute_process_result(
        process_result: FallibleExecuteProcessResult,
        *,
        coverage_data: Optional["CoverageData"] = None,
    ) -> "TestResult":
        return TestResult(
            status=Status.SUCCESS if process_result.exit_code == 0 else Status.FAILURE,
            stdout=process_result.stdout.decode(),
            stderr=process_result.stderr.decode(),
            coverage_data=coverage_data,
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
        adaptor_with_origin: TargetAdaptorWithOrigin, *, union_membership: UnionMembership,
    ) -> bool:
        is_test_target = union_membership.is_member(TestTarget, adaptor_with_origin)
        is_not_a_glob = isinstance(
            adaptor_with_origin.origin, (SingleAddress, FilesystemLiteralSpec)
        )
        return adaptor_with_origin.adaptor.has_sources() and (is_test_target or is_not_a_glob)


@dataclass(frozen=True)
class AddressAndDebugRequest:
    address: Address
    request: TestDebugRequest


class CoverageData(ABC):
    """Base class for inputs to a coverage report.

    Subclasses should add whichever fields they require - snapshots of coverage output or xml files, etc.
    """

    @property
    @abstractmethod
    def batch_cls(self) -> Type["CoverageDataBatch"]:
        pass


@union
class CoverageDataBatch:
    pass


@dataclass(frozen=True)
class CoverageReport:
    result_digest: Digest
    directory_to_materialize_to: PurePath


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
    workspace: Workspace,
) -> Test:
    if options.values.debug:
        address_with_origin = addresses_with_origins.expect_single()
        addr_debug_request = await Get[AddressAndDebugRequest](
            AddressWithOrigin, address_with_origin
        )
        result = runner.run_local_interactive_process(addr_debug_request.request.ipr)
        return Test(result.process_exit_code)

    results = await MultiGet(
        Get[AddressAndTestResult](AddressWithOrigin, address_with_origin)
        for address_with_origin in addresses_with_origins
    )

    if options.values.run_coverage:
        # TODO: consider warning if a user uses `--coverage` but the language backend does not
        # provide coverage support. This might be too chatty to be worth doing?
        results_with_coverage = [
            x
            for x in results
            if x.test_result is not None and x.test_result.coverage_data is not None
        ]
        coverage_data_collections = itertools.groupby(
            results_with_coverage,
            lambda address_and_test_result: address_and_test_result.test_result.coverage_data.batch_cls,  # type: ignore[union-attr]
        )

        coverage_reports = await MultiGet(
            Get[CoverageReport](
                CoverageDataBatch, coverage_batch_cls(tuple(addresses_and_test_results))  # type: ignore[call-arg]
            )
            for coverage_batch_cls, addresses_and_test_results in coverage_data_collections
        )
        for report in coverage_reports:
            workspace.materialize_directory(
                DirectoryToMaterialize(
                    report.result_digest, path_prefix=str(report.directory_to_materialize_to),
                )
            )
            console.print_stdout(f"Wrote coverage report to `{report.directory_to_materialize_to}`")

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
    target_with_origin: HydratedTargetWithOrigin, union_membership: UnionMembership,
) -> AddressAndTestResult:
    adaptor = target_with_origin.target.adaptor
    adaptor_with_origin = TargetAdaptorWithOrigin.create(
        adaptor=adaptor, origin=target_with_origin.origin
    )

    if not AddressAndTestResult.is_testable(adaptor_with_origin, union_membership=union_membership):
        return AddressAndTestResult(adaptor.address, None)

    # TODO(#6004): when streaming to live TTY, rely on V2 UI for this information. When not a
    # live TTY, periodically dump heavy hitters to stderr. See
    # https://github.com/pantsbuild/pants/issues/6004#issuecomment-492699898.
    logger.info(f"Starting tests: {adaptor.address.reference()}")
    # NB: This has the effect of "casting" a TargetAdaptorWithOrigin to a member of the TestTarget
    # union. If the adaptor is not a member of the union, the engine will fail at runtime with a
    # useful error message.
    result = await Get[TestResult](TestTarget, adaptor_with_origin)
    logger.info(
        f"Tests {'succeeded' if result.status == Status.SUCCESS else 'failed'}: "
        f"{adaptor.address.reference()}"
    )
    return AddressAndTestResult(adaptor.address, result)


@rule
async def coordinator_of_debug_tests(
    target_with_origin: HydratedTargetWithOrigin,
) -> AddressAndDebugRequest:
    adaptor = target_with_origin.target.adaptor
    adaptor_with_origin = TargetAdaptorWithOrigin.create(
        adaptor=adaptor, origin=target_with_origin.origin
    )
    logger.info(f"Starting tests in debug mode: {adaptor.address.reference()}")
    request = await Get[TestDebugRequest](TestTarget, adaptor_with_origin)
    return AddressAndDebugRequest(adaptor.address, request)


def rules():
    return [
        coordinator_of_tests,
        coordinator_of_debug_tests,
        run_tests,
    ]
