# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from textwrap import dedent
from typing import List, Optional, Tuple, Type, cast

from pants.base.specs import SingleAddress
from pants.core.goals.test import (
    AddressAndTestResult,
    ConsoleCoverageReport,
    CoverageData,
    CoverageDataCollection,
    CoverageReports,
    Status,
    Test,
    TestDebugRequest,
    TestFieldSet,
    TestOptions,
    TestResult,
    WrappedTestFieldSet,
    run_tests,
)
from pants.core.util_rules.filter_empty_sources import (
    FieldSetsWithSources,
    FieldSetsWithSourcesRequest,
)
from pants.engine.addresses import Address
from pants.engine.fs import Digest, FileContent, InputFilesContent, Workspace
from pants.engine.interactive_process import InteractiveProcess, InteractiveRunner
from pants.engine.target import (
    Sources,
    Target,
    TargetsToValidFieldSets,
    TargetsToValidFieldSetsRequest,
    TargetWithOrigin,
)
from pants.engine.unions import UnionMembership
from pants.testutil.engine.util import MockConsole, MockGet, create_goal_subsystem, run_rule
from pants.testutil.test_base import TestBase


class MockTarget(Target):
    alias = "mock_target"
    core_fields = (Sources,)


@dataclass(frozen=True)
class MockCoverageData(CoverageData):
    address: Address


class MockCoverageDataCollection(CoverageDataCollection):
    element_type = MockCoverageData


class MockTestFieldSet(TestFieldSet, metaclass=ABCMeta):
    required_fields = (Sources,)

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
            status=self.status(self.address),
            stdout=self.stdout(self.address),
            stderr=self.stderr(self.address),
            coverage_data=MockCoverageData(self.address),
            xml_results=None,
        )


class SuccessfulFieldSet(MockTestFieldSet):
    @staticmethod
    def status(_: Address) -> Status:
        return Status.SUCCESS

    @staticmethod
    def stdout(address: Address) -> str:
        return f"Successful test target: Passed for {address}!"


class ConditionallySucceedsFieldSet(MockTestFieldSet):
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


class TestTest(TestBase):
    def make_interactive_process(self) -> InteractiveProcess:
        input_files_content = InputFilesContent(
            (FileContent(path="program.py", content=b"def test(): pass"),)
        )
        digest = self.request_single_product(Digest, input_files_content)
        return InteractiveProcess(["/usr/bin/python", "program.py"], input_digest=digest)

    @staticmethod
    def make_target_with_origin(address: Optional[Address] = None) -> TargetWithOrigin:
        if address is None:
            address = Address.parse(":tests")
        return TargetWithOrigin(
            MockTarget({}, address=address),
            origin=SingleAddress(directory=address.spec_path, name=address.target_name),
        )

    def run_test_rule(
        self,
        *,
        field_set: Type[TestFieldSet],
        targets: List[TargetWithOrigin],
        debug: bool = False,
        use_coverage: bool = False,
        include_sources: bool = True,
        valid_targets: bool = True,
    ) -> Tuple[int, str]:
        console = MockConsole(use_colors=False)
        options = create_goal_subsystem(TestOptions, debug=debug, use_coverage=use_coverage)
        interactive_runner = InteractiveRunner(self.scheduler)
        workspace = Workspace(self.scheduler)
        union_membership = UnionMembership(
            {TestFieldSet: [field_set], CoverageDataCollection: [MockCoverageDataCollection]}
        )

        def mock_find_valid_field_sets(
            _: TargetsToValidFieldSetsRequest,
        ) -> TargetsToValidFieldSets:
            if not valid_targets:
                return TargetsToValidFieldSets({})
            return TargetsToValidFieldSets(
                {
                    tgt_with_origin: [field_set.create(tgt_with_origin)]
                    for tgt_with_origin in targets
                }
            )

        def mock_coordinator_of_tests(
            wrapped_field_set: WrappedTestFieldSet,
        ) -> AddressAndTestResult:
            field_set = cast(MockTestFieldSet, wrapped_field_set.field_set)
            return AddressAndTestResult(
                address=field_set.address, test_result=field_set.test_result
            )

        def mock_coverage_report_generation(
            coverage_data_collection: MockCoverageDataCollection,
        ) -> CoverageReports:
            addresses = ", ".join(
                coverage_data.address.spec for coverage_data in coverage_data_collection
            )
            console_report = ConsoleCoverageReport(f"Ran coverage on {addresses}")
            return CoverageReports(reports=(console_report,))

        result: Test = run_rule(
            run_tests,
            rule_args=[console, options, interactive_runner, workspace, union_membership],
            mock_gets=[
                MockGet(
                    product_type=TargetsToValidFieldSets,
                    subject_type=TargetsToValidFieldSetsRequest,
                    mock=mock_find_valid_field_sets,
                ),
                MockGet(
                    product_type=AddressAndTestResult,
                    subject_type=WrappedTestFieldSet,
                    mock=lambda wrapped_config: mock_coordinator_of_tests(wrapped_config),
                ),
                MockGet(
                    product_type=TestDebugRequest,
                    subject_type=TestFieldSet,
                    mock=lambda _: TestDebugRequest(self.make_interactive_process()),
                ),
                MockGet(
                    product_type=FieldSetsWithSources,
                    subject_type=FieldSetsWithSourcesRequest,
                    mock=lambda field_sets: FieldSetsWithSources(
                        field_sets if include_sources else ()
                    ),
                ),
                MockGet(
                    product_type=CoverageReports,
                    subject_type=CoverageDataCollection,
                    mock=mock_coverage_report_generation,
                ),
            ],
            union_membership=union_membership,
        )
        assert not console.stdout.getvalue()
        return result.exit_code, console.stderr.getvalue()

    def test_empty_target_noops(self) -> None:
        exit_code, stderr = self.run_test_rule(
            field_set=SuccessfulFieldSet,
            targets=[self.make_target_with_origin()],
            include_sources=False,
        )
        assert exit_code == 0
        assert stderr.strip() == ""

    def test_invalid_target_noops(self) -> None:
        exit_code, stderr = self.run_test_rule(
            field_set=SuccessfulFieldSet,
            targets=[self.make_target_with_origin()],
            valid_targets=False,
        )
        assert exit_code == 0
        assert stderr.strip() == ""

    def test_single_target(self) -> None:
        address = Address.parse(":tests")
        exit_code, stderr = self.run_test_rule(
            field_set=SuccessfulFieldSet, targets=[self.make_target_with_origin(address)]
        )
        assert exit_code == 0
        # NB: We don't render a summary when only running one target.
        assert stderr == dedent(
            f"""\
            ✓ {address}
            {SuccessfulFieldSet.stdout(address)}
            """
        )

    def test_multiple_targets(self) -> None:
        good_address = Address.parse(":good")
        bad_address = Address.parse(":bad")

        exit_code, stderr = self.run_test_rule(
            field_set=ConditionallySucceedsFieldSet,
            targets=[
                self.make_target_with_origin(good_address),
                self.make_target_with_origin(bad_address),
            ],
        )
        assert exit_code == 1
        assert stderr == dedent(
            f"""\
            ✓ {good_address}
            {ConditionallySucceedsFieldSet.stdout(good_address)}

            𐄂 {bad_address}
            {ConditionallySucceedsFieldSet.stderr(bad_address)}

            {good_address}                                                                         .....   SUCCESS
            {bad_address}                                                                          .....   FAILURE
            """
        )

    def test_debug_target(self) -> None:
        exit_code, _ = self.run_test_rule(
            field_set=SuccessfulFieldSet, targets=[self.make_target_with_origin()], debug=True,
        )
        assert exit_code == 0

    def test_coverage(self) -> None:
        addr1 = Address.parse(":t1")
        addr2 = Address.parse(":t2")
        exit_code, stderr = self.run_test_rule(
            field_set=SuccessfulFieldSet,
            targets=[self.make_target_with_origin(addr1), self.make_target_with_origin(addr2)],
            use_coverage=True,
        )
        assert exit_code == 0
        assert stderr.strip().endswith(f"Ran coverage on {addr1.spec}, {addr2.spec}")
