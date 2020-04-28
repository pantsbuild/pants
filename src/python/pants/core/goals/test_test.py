# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta, abstractmethod
from pathlib import PurePath
from textwrap import dedent
from typing import List, Optional, Tuple, Type, cast

from pants.base.specs import SingleAddress
from pants.core.goals.test import (
    AddressAndTestResult,
    CoverageDataCollection,
    CoverageReport,
    FilesystemCoverageReport,
    Status,
    Test,
    TestConfiguration,
    TestDebugRequest,
    TestOptions,
    TestResult,
    WrappedTestConfiguration,
    run_tests,
)
from pants.core.util_rules.filter_empty_sources import (
    ConfigurationsWithSources,
    ConfigurationsWithSourcesRequest,
)
from pants.engine.addresses import Address
from pants.engine.fs import (
    EMPTY_DIRECTORY_DIGEST,
    Digest,
    FileContent,
    InputFilesContent,
    Workspace,
)
from pants.engine.interactive_runner import InteractiveProcessRequest, InteractiveRunner
from pants.engine.target import (
    Sources,
    Target,
    TargetsToValidConfigurations,
    TargetsToValidConfigurationsRequest,
    TargetWithOrigin,
)
from pants.engine.unions import UnionMembership
from pants.testutil.engine.util import MockConsole, MockGet, create_goal_subsystem, run_rule
from pants.testutil.test_base import TestBase


class MockTarget(Target):
    alias = "mock_target"
    core_fields = (Sources,)


class MockTestConfiguration(TestConfiguration, metaclass=ABCMeta):
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
            coverage_data=None,
            xml_results=None,
        )


class SuccessfulConfiguration(MockTestConfiguration):
    @staticmethod
    def status(_: Address) -> Status:
        return Status.SUCCESS

    @staticmethod
    def stdout(address: Address) -> str:
        return f"Successful test target: Passed for {address}!"


class ConditionallySucceedsConfiguration(MockTestConfiguration):
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
            MockTarget({}, address=address),
            origin=SingleAddress(directory=address.spec_path, name=address.target_name),
        )

    def run_test_rule(
        self,
        *,
        config: Type[TestConfiguration],
        targets: List[TargetWithOrigin],
        debug: bool = False,
        include_sources: bool = True,
        valid_targets: bool = True,
    ) -> Tuple[int, str]:
        console = MockConsole(use_colors=False)
        options = create_goal_subsystem(TestOptions, debug=debug, run_coverage=False)
        interactive_runner = InteractiveRunner(self.scheduler)
        workspace = Workspace(self.scheduler)
        union_membership = UnionMembership({TestConfiguration: [config]})

        def mock_find_valid_configs(
            _: TargetsToValidConfigurationsRequest,
        ) -> TargetsToValidConfigurations:
            if not valid_targets:
                return TargetsToValidConfigurations({})
            return TargetsToValidConfigurations(
                {tgt_with_origin: [config.create(tgt_with_origin)] for tgt_with_origin in targets}
            )

        def mock_coordinator_of_tests(
            wrapped_config: WrappedTestConfiguration,
        ) -> AddressAndTestResult:
            config = cast(MockTestConfiguration, wrapped_config.config)
            return AddressAndTestResult(address=config.address, test_result=config.test_result)

        result: Test = run_rule(
            run_tests,
            rule_args=[console, options, interactive_runner, workspace, union_membership],
            mock_gets=[
                MockGet(
                    product_type=TargetsToValidConfigurations,
                    subject_type=TargetsToValidConfigurationsRequest,
                    mock=mock_find_valid_configs,
                ),
                MockGet(
                    product_type=AddressAndTestResult,
                    subject_type=WrappedTestConfiguration,
                    mock=lambda wrapped_config: mock_coordinator_of_tests(wrapped_config),
                ),
                MockGet(
                    product_type=TestDebugRequest,
                    subject_type=TestConfiguration,
                    mock=lambda _: TestDebugRequest(self.make_ipr()),
                ),
                MockGet(
                    product_type=ConfigurationsWithSources,
                    subject_type=ConfigurationsWithSourcesRequest,
                    mock=lambda configs: ConfigurationsWithSources(
                        configs if include_sources else ()
                    ),
                ),
                MockGet(
                    product_type=CoverageReport,
                    subject_type=CoverageDataCollection,
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
            config=SuccessfulConfiguration,
            targets=[self.make_target_with_origin()],
            include_sources=False,
        )
        assert exit_code == 0
        assert stdout.strip() == ""

    def test_invalid_target_noops(self) -> None:
        exit_code, stdout = self.run_test_rule(
            config=SuccessfulConfiguration,
            targets=[self.make_target_with_origin()],
            valid_targets=False,
        )
        assert exit_code == 0
        assert stdout.strip() == ""

    def test_single_target(self) -> None:
        address = Address.parse(":tests")
        exit_code, stdout = self.run_test_rule(
            config=SuccessfulConfiguration, targets=[self.make_target_with_origin(address)]
        )
        assert exit_code == 0
        assert stdout == dedent(
            f"""\
            {address} stdout:
            {SuccessfulConfiguration.stdout(address)}

            {address}                                                                        .....   SUCCESS
            """
        )

    def test_multiple_targets(self) -> None:
        good_address = Address.parse(":good")
        bad_address = Address.parse(":bad")

        exit_code, stdout = self.run_test_rule(
            config=ConditionallySucceedsConfiguration,
            targets=[
                self.make_target_with_origin(good_address),
                self.make_target_with_origin(bad_address),
            ],
        )
        assert exit_code == 1
        assert stdout == dedent(
            f"""\
            {good_address} stdout:
            {ConditionallySucceedsConfiguration.stdout(good_address)}
            {bad_address} stderr:
            {ConditionallySucceedsConfiguration.stderr(bad_address)}

            {good_address}                                                                         .....   SUCCESS
            {bad_address}                                                                          .....   FAILURE
            """
        )

    def test_debug_target(self) -> None:
        exit_code, stdout = self.run_test_rule(
            config=SuccessfulConfiguration, targets=[self.make_target_with_origin()], debug=True,
        )
        assert exit_code == 0
