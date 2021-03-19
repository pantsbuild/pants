# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from textwrap import dedent
from typing import List, Optional, Tuple, Type

import pytest

from pants.core.goals.test import (
    ConsoleCoverageReport,
    CoverageData,
    CoverageDataCollection,
    CoverageReports,
    EnrichedTestResult,
    ShowOutput,
    Test,
    TestDebugRequest,
    TestFieldSet,
    TestSubsystem,
    run_tests,
)
from pants.core.util_rules.distdir import DistDir
from pants.core.util_rules.filter_empty_sources import (
    FieldSetsWithSources,
    FieldSetsWithSourcesRequest,
)
from pants.engine.addresses import Address
from pants.engine.desktop import OpenFiles, OpenFilesRequest
from pants.engine.fs import (
    EMPTY_DIGEST,
    EMPTY_FILE_DIGEST,
    CreateDigest,
    Digest,
    FileContent,
    MergeDigests,
    Workspace,
)
from pants.engine.process import InteractiveProcess, InteractiveRunner
from pants.engine.target import (
    Sources,
    Target,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
)
from pants.engine.unions import UnionMembership
from pants.testutil.option_util import create_goal_subsystem
from pants.testutil.rule_runner import MockGet, RuleRunner, mock_console, run_rule_with_mocks
from pants.util.logging import LogLevel


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
    def exit_code(_: Address) -> int:
        pass

    @property
    def test_result(self) -> EnrichedTestResult:
        return EnrichedTestResult(
            exit_code=self.exit_code(self.address),
            stdout="",
            stdout_digest=EMPTY_FILE_DIGEST,
            stderr="",
            stderr_digest=EMPTY_FILE_DIGEST,
            address=self.address,
            coverage_data=MockCoverageData(self.address),
            output_setting=ShowOutput.ALL,
        )


class SuccessfulFieldSet(MockTestFieldSet):
    @staticmethod
    def exit_code(_: Address) -> int:
        return 0


class ConditionallySucceedsFieldSet(MockTestFieldSet):
    @staticmethod
    def exit_code(address: Address) -> int:
        return 27 if address.target_name == "bad" else 0


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner()


def make_target(address: Optional[Address] = None) -> Target:
    if address is None:
        address = Address("", target_name="tests")
    return MockTarget({}, address=address)


def run_test_rule(
    rule_runner: RuleRunner,
    *,
    field_set: Type[TestFieldSet],
    targets: List[Target],
    debug: bool = False,
    use_coverage: bool = False,
    output: ShowOutput = ShowOutput.ALL,
    include_sources: bool = True,
    valid_targets: bool = True,
) -> Tuple[int, str]:
    test_subsystem = create_goal_subsystem(
        TestSubsystem,
        debug=debug,
        use_coverage=use_coverage,
        output=output,
        extra_env_vars=[],
    )
    interactive_runner = InteractiveRunner(rule_runner.scheduler)
    workspace = Workspace(rule_runner.scheduler)
    union_membership = UnionMembership(
        {TestFieldSet: [field_set], CoverageDataCollection: [MockCoverageDataCollection]}
    )

    def mock_find_valid_field_sets(
        _: TargetRootsToFieldSetsRequest,
    ) -> TargetRootsToFieldSets:
        if not valid_targets:
            return TargetRootsToFieldSets({})
        return TargetRootsToFieldSets({tgt: [field_set.create(tgt)] for tgt in targets})

    def mock_debug_request(_: TestFieldSet) -> TestDebugRequest:
        digest = rule_runner.request(
            Digest, [CreateDigest((FileContent(path="program.py", content=b"def test(): pass"),))]
        )
        process = InteractiveProcess(["/usr/bin/python", "program.py"], input_digest=digest)
        return TestDebugRequest(process)

    def mock_coverage_report_generation(
        coverage_data_collection: MockCoverageDataCollection,
    ) -> CoverageReports:
        addresses = ", ".join(
            coverage_data.address.spec for coverage_data in coverage_data_collection
        )
        console_report = ConsoleCoverageReport(f"Ran coverage on {addresses}")
        return CoverageReports(reports=(console_report,))

    with mock_console(rule_runner.options_bootstrapper) as (console, stdio_reader):
        result: Test = run_rule_with_mocks(
            run_tests,
            rule_args=[
                console,
                test_subsystem,
                interactive_runner,
                workspace,
                union_membership,
                DistDir(relpath=Path("dist")),
            ],
            mock_gets=[
                MockGet(
                    output_type=TargetRootsToFieldSets,
                    input_type=TargetRootsToFieldSetsRequest,
                    mock=mock_find_valid_field_sets,
                ),
                MockGet(
                    output_type=EnrichedTestResult,
                    input_type=TestFieldSet,
                    mock=lambda fs: fs.test_result,
                ),
                MockGet(
                    output_type=TestDebugRequest,
                    input_type=TestFieldSet,
                    mock=mock_debug_request,
                ),
                MockGet(
                    output_type=FieldSetsWithSources,
                    input_type=FieldSetsWithSourcesRequest,
                    mock=lambda field_sets: FieldSetsWithSources(
                        field_sets if include_sources else ()
                    ),
                ),
                # Merge XML results.
                MockGet(
                    output_type=Digest,
                    input_type=MergeDigests,
                    mock=lambda _: EMPTY_DIGEST,
                ),
                MockGet(
                    output_type=CoverageReports,
                    input_type=CoverageDataCollection,
                    mock=mock_coverage_report_generation,
                ),
                MockGet(
                    output_type=OpenFiles,
                    input_type=OpenFilesRequest,
                    mock=lambda _: OpenFiles(()),
                ),
            ],
            union_membership=union_membership,
        )
        assert not stdio_reader.get_stdout()
        return result.exit_code, stdio_reader.get_stderr()


def test_empty_target_noops(rule_runner: RuleRunner) -> None:
    exit_code, stderr = run_test_rule(
        rule_runner,
        field_set=SuccessfulFieldSet,
        targets=[make_target()],
        include_sources=False,
    )
    assert exit_code == 0
    assert stderr.strip() == ""


def test_invalid_target_noops(rule_runner: RuleRunner) -> None:
    exit_code, stderr = run_test_rule(
        rule_runner,
        field_set=SuccessfulFieldSet,
        targets=[make_target()],
        valid_targets=False,
    )
    assert exit_code == 0
    assert stderr.strip() == ""


def test_summary(rule_runner: RuleRunner) -> None:
    good_address = Address("", target_name="good")
    bad_address = Address("", target_name="bad")

    exit_code, stderr = run_test_rule(
        rule_runner,
        field_set=ConditionallySucceedsFieldSet,
        targets=[make_target(good_address), make_target(bad_address)],
    )
    assert exit_code == ConditionallySucceedsFieldSet.exit_code(bad_address)
    assert stderr == dedent(
        """\

        ✓ //:good succeeded.
        𐄂 //:bad failed.
        """
    )


def test_debug_target(rule_runner: RuleRunner) -> None:
    exit_code, _ = run_test_rule(
        rule_runner,
        field_set=SuccessfulFieldSet,
        targets=[make_target()],
        debug=True,
    )
    assert exit_code == 0


def test_coverage(rule_runner: RuleRunner) -> None:
    addr1 = Address("", target_name="t1")
    addr2 = Address("", target_name="t2")
    exit_code, stderr = run_test_rule(
        rule_runner,
        field_set=SuccessfulFieldSet,
        targets=[make_target(addr1), make_target(addr2)],
        use_coverage=True,
    )
    assert exit_code == 0
    assert stderr.strip().endswith(f"Ran coverage on {addr1.spec}, {addr2.spec}")


def sort_results() -> None:
    create_test_result = partial(
        EnrichedTestResult,
        stdout="",
        stdout_digest=EMPTY_FILE_DIGEST,
        stderr="",
        stderr_digest=EMPTY_FILE_DIGEST,
        output_setting=ShowOutput.ALL,
    )
    skip1 = create_test_result(exit_code=None, address=Address("t1"))
    skip2 = create_test_result(exit_code=None, address=Address("t2"))
    success1 = create_test_result(exit_code=0, address=Address("t1"))
    success2 = create_test_result(exit_code=0, address=Address("t2"))
    fail1 = create_test_result(exit_code=1, address=Address("t1"))
    fail2 = create_test_result(exit_code=1, address=Address("t2"))
    assert sorted([fail2, success2, skip2, fail1, success1, skip1]) == [
        skip1,
        skip2,
        success1,
        success2,
        fail1,
        fail2,
    ]


def assert_streaming_output(
    *,
    exit_code: Optional[int],
    stdout: str = "stdout",
    stderr: str = "stderr",
    output_setting: ShowOutput = ShowOutput.ALL,
    expected_level: LogLevel,
    expected_message: str,
) -> None:
    result = EnrichedTestResult(
        exit_code=exit_code,
        stdout=stdout,
        stdout_digest=EMPTY_FILE_DIGEST,
        stderr=stderr,
        stderr_digest=EMPTY_FILE_DIGEST,
        output_setting=output_setting,
        address=Address("demo_test"),
    )
    assert result.level() == expected_level
    assert result.message() == expected_message


def test_streaming_output_skip() -> None:
    assert_streaming_output(
        exit_code=None,
        stdout="",
        stderr="",
        expected_level=LogLevel.DEBUG,
        expected_message="demo_test skipped.",
    )


def test_streaming_output_success() -> None:
    assert_success_streamed = partial(
        assert_streaming_output, exit_code=0, expected_level=LogLevel.INFO
    )
    assert_success_streamed(
        expected_message=dedent(
            """\
            demo_test succeeded.
            stdout
            stderr

            """
        ),
    )
    assert_success_streamed(
        output_setting=ShowOutput.FAILED, expected_message="demo_test succeeded."
    )
    assert_success_streamed(output_setting=ShowOutput.NONE, expected_message="demo_test succeeded.")


def test_streaming_output_failure() -> None:
    assert_failure_streamed = partial(
        assert_streaming_output, exit_code=1, expected_level=LogLevel.WARN
    )
    message = dedent(
        """\
        demo_test failed (exit code 1).
        stdout
        stderr

        """
    )
    assert_failure_streamed(expected_message=message)
    assert_failure_streamed(output_setting=ShowOutput.FAILED, expected_message=message)
    assert_failure_streamed(
        output_setting=ShowOutput.NONE, expected_message="demo_test failed (exit code 1)."
    )
