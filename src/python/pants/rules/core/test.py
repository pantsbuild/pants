# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath
from typing import Iterable, Optional, Type

from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE
from pants.build_graph.address import Address
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.interactive_runner import InteractiveProcessRequest, InteractiveRunner
from pants.engine.isolated_process import FallibleExecuteProcessResult
from pants.engine.legacy.graph import HydratedTargetsWithOrigins
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
@dataclass(frozen=True)  # type: ignore[misc]   # https://github.com/python/mypy/issues/5374
class TestRunner(ABC):
    adaptor_with_origin: TargetAdaptorWithOrigin

    __test__ = False

    @staticmethod
    @abstractmethod
    def is_valid_target(_: TargetAdaptorWithOrigin) -> bool:
        """Return True if the test runner can meaningfully operate on this target."""


# NB: This is only used for the sake of coordinator_of_tests. Consider inlining that rule so that
# we can remove this wrapper type.
@dataclass(frozen=True)
class WrappedTestRunner:
    runner: TestRunner


@dataclass(frozen=True)
class AddressAndTestResult:
    address: Address
    test_result: TestResult


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

    required_union_implementations = (TestRunner,)

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

    __test__ = False


@goal_rule
async def run_tests(
    console: Console,
    options: TestOptions,
    runner: InteractiveRunner,
    targets_with_origins: HydratedTargetsWithOrigins,
    workspace: Workspace,
    union_membership: UnionMembership,
) -> Test:
    test_runners: Iterable[Type[TestRunner]] = union_membership.union_rules[TestRunner]

    if options.values.debug:
        target_with_origin = targets_with_origins.expect_single()
        adaptor_with_origin = TargetAdaptorWithOrigin.create(
            target_with_origin.target.adaptor, target_with_origin.origin
        )
        address = adaptor_with_origin.adaptor.address
        valid_test_runners = [
            test_runner
            for test_runner in test_runners
            if test_runner.is_valid_target(adaptor_with_origin)
        ]
        if not valid_test_runners:
            raise ValueError(f"No valid test runner for {address}.")
        if len(valid_test_runners) > 1:
            raise ValueError(
                f"Multiple possible test runners for {address} "
                f"({', '.join(test_runner.__name__ for test_runner in valid_test_runners)})."
            )
        test_runner = valid_test_runners[0]
        logger.info(f"Starting test in debug mode: {address.reference()}")
        request = await Get[TestDebugRequest](TestRunner, test_runner(adaptor_with_origin))
        debug_result = runner.run_local_interactive_process(request.ipr)
        return Test(debug_result.process_exit_code)

    adaptors_with_origins = tuple(
        TargetAdaptorWithOrigin.create(target_with_origin.target.adaptor, target_with_origin.origin)
        for target_with_origin in targets_with_origins
        if target_with_origin.target.adaptor.has_sources()
    )

    results = await MultiGet(
        Get[AddressAndTestResult](
            WrappedTestRunner, WrappedTestRunner(test_runner(adaptor_with_origin))
        )
        for adaptor_with_origin in adaptors_with_origins
        for test_runner in test_runners
        if test_runner.is_valid_target(adaptor_with_origin)
    )

    if options.values.run_coverage:
        # TODO: consider warning if a user uses `--coverage` but the language backend does not
        # provide coverage support. This might be too chatty to be worth doing?
        results_with_coverage = [x for x in results if x.test_result.coverage_data is not None]
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
    for result in results:
        if result.test_result.status == Status.FAILURE:
            did_any_fail = True
        if result.test_result.stdout:
            console.write_stdout(
                f"{result.address.reference()} stdout:\n{result.test_result.stdout}\n"
            )
        if result.test_result.stderr:
            # NB: we write to stdout, rather than to stderr, to avoid potential issues interleaving
            # the two streams.
            console.write_stdout(
                f"{result.address.reference()} stderr:\n{result.test_result.stderr}\n"
            )

    console.write_stdout("\n")

    for result in results:
        console.print_stdout(
            f"{result.address.reference():80}.....{result.test_result.status.value:>10}"
        )

    if did_any_fail:
        console.print_stderr(console.red("\nTests failed"))
        exit_code = PANTS_FAILED_EXIT_CODE
    else:
        exit_code = PANTS_SUCCEEDED_EXIT_CODE

    return Test(exit_code)


@rule
async def coordinator_of_tests(wrapped_test_runner: WrappedTestRunner) -> AddressAndTestResult:
    test_runner = wrapped_test_runner.runner
    adaptor_with_origin = test_runner.adaptor_with_origin
    adaptor = adaptor_with_origin.adaptor

    # TODO(#6004): when streaming to live TTY, rely on V2 UI for this information. When not a
    # live TTY, periodically dump heavy hitters to stderr. See
    # https://github.com/pantsbuild/pants/issues/6004#issuecomment-492699898.
    logger.info(f"Starting tests: {adaptor.address.reference()}")
    # NB: This has the effect of "casting" a TargetAdaptorWithOrigin to a member of the TestTarget
    # union. If the adaptor is not a member of the union, the engine will fail at runtime with a
    # useful error message.
    result = await Get[TestResult](TestRunner, test_runner)
    logger.info(
        f"Tests {'succeeded' if result.status == Status.SUCCESS else 'failed'}: "
        f"{adaptor.address.reference()}"
    )
    return AddressAndTestResult(adaptor.address, result)


def rules():
    return [coordinator_of_tests, run_tests]
