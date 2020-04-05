# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta, abstractmethod
from pathlib import PurePath
from textwrap import dedent
from typing import List, Tuple, Type
from unittest.mock import Mock

import pytest

from pants.base.exceptions import ResolveError
from pants.build_graph.address import Address
from pants.engine.fs import (
    EMPTY_DIRECTORY_DIGEST,
    Digest,
    FileContent,
    InputFilesContent,
    Workspace,
)
from pants.engine.interactive_runner import InteractiveProcessRequest, InteractiveRunner
from pants.engine.legacy.graph import HydratedTargetsWithOrigins, HydratedTargetWithOrigin
from pants.engine.legacy.structs import TargetAdaptorWithOrigin
from pants.engine.rules import UnionMembership
from pants.rules.core.fmt_test import FmtTest
from pants.rules.core.test import (
    AddressAndTestResult,
    CoverageDataBatch,
    CoverageReport,
    FilesystemCoverageReport,
    Status,
    Test,
    TestDebugRequest,
    TestResult,
    TestRunner,
    WrappedTestRunner,
    run_tests,
)
from pants.testutil.engine.util import MockConsole, MockGet, run_rule
from pants.testutil.test_base import TestBase
from pants.util.ordered_set import OrderedSet


# TODO(#9141): replace this with a proper util to create `GoalSubsystem`s
class MockOptions:
    def __init__(self, **values):
        self.values = Mock(**values)


class MockTestRunner(TestRunner, metaclass=ABCMeta):
    @staticmethod
    def is_valid_target(_: TargetAdaptorWithOrigin) -> bool:
        return True

    @staticmethod
    @abstractmethod
    def status(_: Address) -> Status:
        pass

    @staticmethod
    def stdout(_: Address) -> str:
        return ""

    @staticmethod
    def stderr(_: Address) -> str:
        return ""

    @property
    def test_result(self) -> TestResult:
        address = self.adaptor_with_origin.adaptor.address
        return TestResult(
            self.status(address), self.stdout(address), self.stderr(address), coverage_data=None
        )


class SuccessfulTestRunner(MockTestRunner):
    @staticmethod
    def status(_: Address) -> Status:
        return Status.SUCCESS

    @staticmethod
    def stdout(address: Address) -> str:
        return f"Successful test runner: Passed for {address}!"


class ConditionallySucceedsTestRunner(MockTestRunner):
    @staticmethod
    def status(address: Address) -> Status:
        return Status.FAILURE if address.target_name == "bad" else Status.SUCCESS

    @staticmethod
    def stdout(address: Address) -> str:
        return (
            f"Conditionally succeeds test runner: Passed for {address}!"
            if address.target_name != "bad"
            else ""
        )

    @staticmethod
    def stderr(address: Address) -> str:
        return (
            f"Conditionally succeeds test runner: Had an issue for {address}! Oh no!"
            if address.target_name == "bad"
            else ""
        )


class InvalidTargetTestRunner(MockTestRunner):
    @staticmethod
    def is_valid_target(_: TargetAdaptorWithOrigin) -> bool:
        return False

    @staticmethod
    def status(_: Address) -> Status:
        return Status.FAILURE


class TestTest(TestBase):
    def make_ipr(self) -> InteractiveProcessRequest:
        input_files_content = InputFilesContent(
            (FileContent(path="program.py", content=b"def test(): pass"),)
        )
        digest = self.request_single_product(Digest, input_files_content)
        return InteractiveProcessRequest(
            argv=("/usr/bin/python", "program.py",), run_in_workspace=False, input_files=digest,
        )

    def run_test_rule(
        self,
        *,
        test_runner: Type[TestRunner],
        targets: List[HydratedTargetWithOrigin],
        debug: bool = False,
    ) -> Tuple[int, str]:
        console = MockConsole(use_colors=False)
        options = MockOptions(debug=debug, run_coverage=False)
        interactive_runner = InteractiveRunner(self.scheduler)
        workspace = Workspace(self.scheduler)
        union_membership = UnionMembership({TestRunner: OrderedSet([test_runner])})

        def mock_coordinator_of_tests(
            wrapped_test_runner: WrappedTestRunner,
        ) -> AddressAndTestResult:
            runner = wrapped_test_runner.runner
            return AddressAndTestResult(
                address=runner.adaptor_with_origin.adaptor.address,
                test_result=runner.test_result,  # type: ignore[attr-defined]
            )

        result: Test = run_rule(
            run_tests,
            rule_args=[
                console,
                options,
                interactive_runner,
                HydratedTargetsWithOrigins(targets),
                workspace,
                union_membership,
            ],
            mock_gets=[
                MockGet(
                    product_type=AddressAndTestResult,
                    subject_type=WrappedTestRunner,
                    mock=lambda wrapped_test_runner: mock_coordinator_of_tests(wrapped_test_runner),
                ),
                MockGet(
                    product_type=TestDebugRequest,
                    subject_type=TestRunner,
                    mock=lambda _: TestDebugRequest(self.make_ipr()),
                ),
                MockGet(
                    product_type=CoverageReport,
                    subject_type=CoverageDataBatch,
                    mock=lambda _: FilesystemCoverageReport(
                        result_digest=EMPTY_DIRECTORY_DIGEST,
                        directory_to_materialize_to=PurePath("mockety/mock"),
                        report_file=None,
                    ),
                ),
            ],
            union_membership=union_membership,
        )
        return result.exit_code, console.stdout.getvalue()

    def test_empty_target_noops(self) -> None:
        exit_code, stdout = self.run_test_rule(
            test_runner=SuccessfulTestRunner,
            targets=[FmtTest.make_hydrated_target_with_origin(include_sources=False)],
        )
        assert exit_code == 0
        assert stdout.strip() == ""

    def test_invalid_target_noops(self) -> None:
        exit_code, stdout = self.run_test_rule(
            test_runner=InvalidTargetTestRunner,
            targets=[FmtTest.make_hydrated_target_with_origin()],
        )
        assert exit_code == 0
        assert stdout.strip() == ""

    def test_single_target(self) -> None:
        target_with_origin = FmtTest.make_hydrated_target_with_origin()
        address = target_with_origin.target.adaptor.address
        exit_code, stdout = self.run_test_rule(
            test_runner=SuccessfulTestRunner, targets=[target_with_origin],
        )
        assert exit_code == 0
        assert stdout == dedent(
            f"""\
            {address} stdout:
            {SuccessfulTestRunner.stdout(address)}

            {address}                                                                       .....   SUCCESS
            """
        )

    def test_multiple_targets(self) -> None:
        good_target = FmtTest.make_hydrated_target_with_origin(name="good")
        good_address = good_target.target.adaptor.address
        bad_target = FmtTest.make_hydrated_target_with_origin(name="bad")
        bad_address = bad_target.target.adaptor.address

        exit_code, stdout = self.run_test_rule(
            test_runner=ConditionallySucceedsTestRunner, targets=[good_target, bad_target],
        )
        assert exit_code == 1
        assert stdout == dedent(
            f"""\
            {good_address} stdout:
            {ConditionallySucceedsTestRunner.stdout(good_address)}
            {bad_address} stderr:
            {ConditionallySucceedsTestRunner.stderr(bad_address)}

            {good_address}                                                                         .....   SUCCESS
            {bad_address}                                                                          .....   FAILURE
            """
        )

    def test_single_debug_target(self) -> None:
        exit_code, stdout = self.run_test_rule(
            test_runner=SuccessfulTestRunner,
            targets=[FmtTest.make_hydrated_target_with_origin()],
            debug=True,
        )
        assert exit_code == 0

    def test_multiple_debug_targets_fail(self) -> None:
        with pytest.raises(ResolveError):
            self.run_test_rule(
                test_runner=SuccessfulTestRunner,
                targets=[
                    FmtTest.make_hydrated_target_with_origin(name="t1"),
                    FmtTest.make_hydrated_target_with_origin(name="t2"),
                ],
                debug=True,
            )
