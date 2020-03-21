# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta, abstractmethod
from pathlib import PurePath
from textwrap import dedent
from typing import List, Optional, Tuple, Type
from unittest.mock import Mock

import pytest

from pants.base.exceptions import ResolveError
from pants.base.specs import SingleAddress
from pants.build_graph.address import Address
from pants.engine.fs import (
    EMPTY_DIRECTORY_DIGEST,
    Digest,
    FileContent,
    InputFilesContent,
    Workspace,
)
from pants.engine.interactive_runner import InteractiveProcessRequest, InteractiveRunner
from pants.engine.rules import UnionMembership
from pants.engine.target import RegisteredTargetTypes, Target, TargetsWithOrigins, TargetWithOrigin
from pants.rules.core.test import (
    AddressAndTestResult,
    CoverageDataBatch,
    CoverageReport,
    FilesystemCoverageReport,
    Status,
    Test,
    TestDebugRequest,
    TestResult,
    TestTarget,
    WrappedTestTarget,
    run_tests,
)
from pants.testutil.engine.util import MockConsole, MockGet, run_rule
from pants.testutil.test_base import TestBase
from pants.util.ordered_set import OrderedSet


# TODO(#9141): replace this with a proper util to create `GoalSubsystem`s
class MockOptions:
    def __init__(self, **values):
        self.values = Mock(**values)


class HaskellTests(Target):
    alias = "haskell_tests"
    core_fields = ()


class MockTestTarget(TestTarget, metaclass=ABCMeta):
    @classmethod
    def is_valid(cls, _: Target) -> bool:
        return True

    @classmethod
    def create(cls, target_with_origin: TargetWithOrigin) -> "MockTestTarget":
        return cls(address=target_with_origin.target.address, origin=target_with_origin.origin)

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
        return TestResult(
            self.status(self.address), self.stdout(self.address), self.stderr(self.address)
        )


class SuccessfulTestTarget(MockTestTarget):
    @staticmethod
    def status(_: Address) -> Status:
        return Status.SUCCESS

    @staticmethod
    def stdout(address: Address) -> str:
        return f"Successful test target: Passed for {address}!"


class ConditionallySucceedsTestTarget(MockTestTarget):
    @staticmethod
    def status(address: Address) -> Status:
        return Status.FAILURE if address.target_name == "bad" else Status.SUCCESS

    @staticmethod
    def stdout(address: Address) -> str:
        return (
            f"Conditionally succeeds test target: Passed for {address}!"
            if address.target_name != "bad"
            else ""
        )

    @staticmethod
    def stderr(address: Address) -> str:
        return (
            f"Conditionally succeeds test target: Had an issue for {address}! Oh no!"
            if address.target_name == "bad"
            else ""
        )


class InvalidTestTarget(MockTestTarget):
    @classmethod
    def is_valid(cls, _: Target) -> bool:
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

    @staticmethod
    def make_target_with_origin(address: Optional[Address] = None) -> TargetWithOrigin:
        if address is None:
            address = Address.parse(":tests")
        return TargetWithOrigin(
            HaskellTests({}, address=address),
            origin=SingleAddress(directory=address.spec_path, name=address.target_name),
        )

    def run_test_rule(
        self,
        *,
        test_target: Type[TestTarget],
        targets: List[TargetWithOrigin],
        debug: bool = False,
    ) -> Tuple[int, str]:
        console = MockConsole(use_colors=False)
        options = MockOptions(debug=debug, run_coverage=False)
        interactive_runner = InteractiveRunner(self.scheduler)
        workspace = Workspace(self.scheduler)
        union_membership = UnionMembership({TestTarget: OrderedSet([test_target])})

        def mock_coordinator_of_tests(
            wrapped_test_runner: WrappedTestTarget,
        ) -> AddressAndTestResult:
            target = wrapped_test_runner.test_target
            return AddressAndTestResult(
                address=target.address,
                test_result=target.test_result,  # type: ignore[attr-defined]
            )

        result: Test = run_rule(
            run_tests,
            rule_args=[
                console,
                options,
                interactive_runner,
                TargetsWithOrigins(targets),
                workspace,
                union_membership,
                RegisteredTargetTypes.create([HaskellTests]),
            ],
            mock_gets=[
                MockGet(
                    product_type=AddressAndTestResult,
                    subject_type=WrappedTestTarget,
                    mock=lambda wrapped_test_target: mock_coordinator_of_tests(wrapped_test_target),
                ),
                MockGet(
                    product_type=TestDebugRequest,
                    subject_type=TestTarget,
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

    def test_invalid_target_noops(self) -> None:
        exit_code, stdout = self.run_test_rule(
            test_target=InvalidTestTarget, targets=[self.make_target_with_origin()],
        )
        assert exit_code == 0
        assert stdout.strip() == ""

    def test_single_target(self) -> None:
        address = Address.parse(":tests")
        exit_code, stdout = self.run_test_rule(
            test_target=SuccessfulTestTarget, targets=[self.make_target_with_origin(address)],
        )
        assert exit_code == 0
        assert stdout == dedent(
            f"""\
            {address} stdout:
            {SuccessfulTestTarget.stdout(address)}

            {address}                                                                        .....   SUCCESS
            """
        )

    def test_multiple_targets(self) -> None:
        good_address = Address.parse(":good")
        bad_address = Address.parse(":bad")

        exit_code, stdout = self.run_test_rule(
            test_target=ConditionallySucceedsTestTarget,
            targets=[
                self.make_target_with_origin(address=good_address),
                self.make_target_with_origin(bad_address),
            ],
        )
        assert exit_code == 1
        assert stdout == dedent(
            f"""\
            {good_address} stdout:
            {ConditionallySucceedsTestTarget.stdout(good_address)}
            {bad_address} stderr:
            {ConditionallySucceedsTestTarget.stderr(bad_address)}

            {good_address}                                                                         .....   SUCCESS
            {bad_address}                                                                          .....   FAILURE
            """
        )

    def test_single_debug_target(self) -> None:
        exit_code, stdout = self.run_test_rule(
            test_target=SuccessfulTestTarget, targets=[self.make_target_with_origin()], debug=True,
        )
        assert exit_code == 0

    def test_multiple_debug_targets_fail(self) -> None:
        with pytest.raises(ResolveError):
            self.run_test_rule(
                test_target=SuccessfulTestTarget,
                targets=[
                    self.make_target_with_origin(Address.parse(":t1")),
                    self.make_target_with_origin(Address.parse(":t2")),
                ],
                debug=True,
            )
