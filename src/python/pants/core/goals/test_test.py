# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from textwrap import dedent

import pytest

from pants.backend.python.goals import package_pex_binary
from pants.backend.python.target_types import PexBinary, PythonSourcesGeneratorTarget
from pants.backend.python.target_types_rules import rules as python_target_type_rules
from pants.backend.python.util_rules import pex_from_targets
from pants.core.goals.test import (
    BuildPackageDependenciesRequest,
    BuiltPackageDependencies,
    ConsoleCoverageReport,
    CoverageData,
    CoverageDataCollection,
    CoverageReports,
    RuntimePackageDependenciesField,
    ShowOutput,
    Test,
    TestDebugAdapterRequest,
    TestDebugRequest,
    TestFieldSet,
    TestResult,
    TestSubsystem,
    TestTimeoutField,
    _format_test_summary,
    build_runtime_package_dependencies,
    run_tests,
)
from pants.core.subsystems.debug_adapter import DebugAdapterSubsystem
from pants.core.util_rules.distdir import DistDir
from pants.engine.addresses import Address
from pants.engine.console import Console
from pants.engine.desktop import OpenFiles, OpenFilesRequest
from pants.engine.fs import (
    EMPTY_DIGEST,
    EMPTY_FILE_DIGEST,
    Digest,
    MergeDigests,
    Snapshot,
    Workspace,
)
from pants.engine.internals.session import RunId
from pants.engine.process import InteractiveProcess, InteractiveProcessResult, ProcessResultMetadata
from pants.engine.target import (
    MultipleSourcesField,
    Target,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
)
from pants.engine.unions import UnionMembership
from pants.testutil.option_util import create_goal_subsystem, create_subsystem
from pants.testutil.rule_runner import (
    MockEffect,
    MockGet,
    QueryRule,
    RuleRunner,
    mock_console,
    run_rule_with_mocks,
)
from pants.util.logging import LogLevel


class MockMultipleSourcesField(MultipleSourcesField):
    pass


class MockTestTimeoutField(TestTimeoutField):
    pass


class MockTarget(Target):
    alias = "mock_target"
    core_fields = (MockMultipleSourcesField,)


@dataclass(frozen=True)
class MockCoverageData(CoverageData):
    address: Address


class MockCoverageDataCollection(CoverageDataCollection):
    element_type = MockCoverageData


class MockTestFieldSet(TestFieldSet, metaclass=ABCMeta):
    required_fields = (MultipleSourcesField,)

    @staticmethod
    @abstractmethod
    def exit_code(_: Address) -> int:
        pass

    @staticmethod
    @abstractmethod
    def skipped(_: Address) -> bool:
        pass

    @property
    def test_result(self) -> TestResult:
        return TestResult(
            exit_code=self.exit_code(self.address),
            stdout="",
            stdout_digest=EMPTY_FILE_DIGEST,
            stderr="",
            stderr_digest=EMPTY_FILE_DIGEST,
            address=self.address,
            coverage_data=MockCoverageData(self.address),
            output_setting=ShowOutput.ALL,
            result_metadata=None
            if self.skipped(self.address)
            else ProcessResultMetadata(999, "ran_locally", 0),
        )


class SuccessfulFieldSet(MockTestFieldSet):
    @staticmethod
    def exit_code(_: Address) -> int:
        return 0

    @staticmethod
    def skipped(_: Address) -> bool:
        return False


class ConditionallySucceedsFieldSet(MockTestFieldSet):
    @staticmethod
    def exit_code(address: Address) -> int:
        return 27 if address.target_name == "bad" else 0

    @staticmethod
    def skipped(address: Address) -> bool:
        return address.target_name == "skipped"


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner()


def make_target(address: Address | None = None) -> Target:
    if address is None:
        address = Address("", target_name="tests")
    return MockTarget({}, address)


def run_test_rule(
    rule_runner: RuleRunner,
    *,
    field_set: type[TestFieldSet],
    targets: list[Target],
    debug: bool = False,
    use_coverage: bool = False,
    report: bool = False,
    report_dir: str = TestSubsystem.default_report_path,
    output: ShowOutput = ShowOutput.ALL,
    valid_targets: bool = True,
    run_id: RunId = RunId(999),
) -> tuple[int, str]:
    test_subsystem = create_goal_subsystem(
        TestSubsystem,
        debug=debug,
        debug_adapter=False,
        use_coverage=use_coverage,
        report=report,
        report_dir=report_dir,
        xml_dir=None,
        output=output,
        extra_env_vars=[],
        shard="",
    )
    debug_adapter_subsystem = create_subsystem(
        DebugAdapterSubsystem,
        host="127.0.0.1",
        port="5678",
    )
    workspace = Workspace(rule_runner.scheduler, _enforce_effects=False)
    union_membership = UnionMembership(
        {
            TestFieldSet: [field_set],
            CoverageDataCollection: [MockCoverageDataCollection],
        }
    )

    def mock_find_valid_field_sets(
        _: TargetRootsToFieldSetsRequest,
    ) -> TargetRootsToFieldSets:
        if not valid_targets:
            return TargetRootsToFieldSets({})
        return TargetRootsToFieldSets({tgt: [field_set.create(tgt)] for tgt in targets})

    def mock_debug_request(_: TestFieldSet) -> TestDebugRequest:
        return TestDebugRequest(InteractiveProcess(["/bin/example"], input_digest=EMPTY_DIGEST))

    def mock_debug_adapter_request(_: TestFieldSet) -> TestDebugAdapterRequest:
        return TestDebugAdapterRequest(
            InteractiveProcess(["/bin/example"], input_digest=EMPTY_DIGEST)
        )

    def mock_coverage_report_generation(
        coverage_data_collection: MockCoverageDataCollection,
    ) -> CoverageReports:
        addresses = ", ".join(
            coverage_data.address.spec for coverage_data in coverage_data_collection
        )
        console_report = ConsoleCoverageReport(
            coverage_insufficient=False, report=f"Ran coverage on {addresses}"
        )
        return CoverageReports(reports=(console_report,))

    with mock_console(rule_runner.options_bootstrapper) as (console, stdio_reader):
        result: Test = run_rule_with_mocks(
            run_tests,
            rule_args=[
                console,
                test_subsystem,
                debug_adapter_subsystem,
                workspace,
                union_membership,
                DistDir(relpath=Path("dist")),
                run_id,
            ],
            mock_gets=[
                MockGet(
                    output_type=TargetRootsToFieldSets,
                    input_type=TargetRootsToFieldSetsRequest,
                    mock=mock_find_valid_field_sets,
                ),
                MockGet(
                    output_type=TestResult,
                    input_type=TestFieldSet,
                    mock=lambda fs: fs.test_result,
                ),
                MockGet(
                    output_type=TestDebugRequest,
                    input_type=TestFieldSet,
                    mock=mock_debug_request,
                ),
                MockGet(
                    output_type=TestDebugAdapterRequest,
                    input_type=TestFieldSet,
                    mock=mock_debug_adapter_request,
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
                MockEffect(
                    output_type=InteractiveProcessResult,
                    input_type=InteractiveProcess,
                    mock=lambda _: InteractiveProcessResult(0),
                ),
            ],
            union_membership=union_membership,
        )
        assert not stdio_reader.get_stdout()
        return result.exit_code, stdio_reader.get_stderr()


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
    skipped_address = Address("", target_name="skipped")

    exit_code, stderr = run_test_rule(
        rule_runner,
        field_set=ConditionallySucceedsFieldSet,
        targets=[make_target(good_address), make_target(bad_address), make_target(skipped_address)],
    )
    assert exit_code == ConditionallySucceedsFieldSet.exit_code(bad_address)
    assert stderr == dedent(
        """\

        ✓ //:good succeeded in 1.00s (memoized).
        ✕ //:bad failed in 1.00s (memoized).
        """
    )


def _assert_test_summary(
    expected: str,
    *,
    exit_code: int | None,
    run_id: int,
    result_metadata: ProcessResultMetadata | None,
) -> None:
    assert expected == _format_test_summary(
        TestResult(
            exit_code=exit_code,
            stdout="",
            stderr="",
            stdout_digest=EMPTY_FILE_DIGEST,
            stderr_digest=EMPTY_FILE_DIGEST,
            address=Address(spec_path="", target_name="dummy_address"),
            output_setting=ShowOutput.FAILED,
            result_metadata=result_metadata,
        ),
        RunId(run_id),
        Console(use_colors=False),
    )


def test_format_summary_remote(rule_runner: RuleRunner) -> None:
    _assert_test_summary(
        "✓ //:dummy_address succeeded in 0.05s (ran remotely).",
        exit_code=0,
        run_id=0,
        result_metadata=ProcessResultMetadata(50, "ran_remotely", 0),
    )


def test_format_summary_local(rule_runner: RuleRunner) -> None:
    _assert_test_summary(
        "✓ //:dummy_address succeeded in 0.05s.",
        exit_code=0,
        run_id=0,
        result_metadata=ProcessResultMetadata(50, "ran_locally", 0),
    )


def test_format_summary_memoized(rule_runner: RuleRunner) -> None:
    _assert_test_summary(
        "✓ //:dummy_address succeeded in 0.05s (memoized).",
        exit_code=0,
        run_id=1234,
        result_metadata=ProcessResultMetadata(50, "ran_locally", 0),
    )


def test_debug_target(rule_runner: RuleRunner) -> None:
    exit_code, _ = run_test_rule(
        rule_runner,
        field_set=SuccessfulFieldSet,
        targets=[make_target()],
        debug=True,
    )
    assert exit_code == 0


def test_report(rule_runner: RuleRunner) -> None:
    addr1 = Address("", target_name="t1")
    addr2 = Address("", target_name="t2")
    exit_code, stderr = run_test_rule(
        rule_runner,
        field_set=SuccessfulFieldSet,
        targets=[make_target(addr1), make_target(addr2)],
        report=True,
    )
    assert exit_code == 0
    assert "Wrote test reports to dist/test/reports" in stderr


def test_report_dir(rule_runner: RuleRunner) -> None:
    report_dir = "dist/test-results"
    addr1 = Address("", target_name="t1")
    addr2 = Address("", target_name="t2")
    exit_code, stderr = run_test_rule(
        rule_runner,
        field_set=SuccessfulFieldSet,
        targets=[make_target(addr1), make_target(addr2)],
        report=True,
        report_dir=report_dir,
    )
    assert exit_code == 0
    assert f"Wrote test reports to {report_dir}" in stderr


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
        TestResult,
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
    exit_code: int | None,
    stdout: str = "stdout",
    stderr: str = "stderr",
    output_setting: ShowOutput = ShowOutput.ALL,
    expected_level: LogLevel,
    expected_message: str,
    result_metadata: ProcessResultMetadata = ProcessResultMetadata(999, "dummy", 0),
) -> None:
    result = TestResult(
        exit_code=exit_code,
        stdout=stdout,
        stdout_digest=EMPTY_FILE_DIGEST,
        stderr=stderr,
        stderr_digest=EMPTY_FILE_DIGEST,
        output_setting=output_setting,
        address=Address("demo_test"),
        result_metadata=result_metadata,
    )
    assert result.level() == expected_level
    assert result.message() == expected_message


def test_streaming_output_skip() -> None:
    assert_streaming_output(
        exit_code=None,
        stdout="",
        stderr="",
        expected_level=LogLevel.DEBUG,
        expected_message="demo_test:demo_test skipped.",
    )


def test_streaming_output_success() -> None:
    assert_success_streamed = partial(
        assert_streaming_output, exit_code=0, expected_level=LogLevel.INFO
    )
    assert_success_streamed(
        expected_message=dedent(
            """\
            demo_test:demo_test succeeded.
            stdout
            stderr

            """
        ),
    )
    assert_success_streamed(
        output_setting=ShowOutput.FAILED, expected_message="demo_test:demo_test succeeded."
    )
    assert_success_streamed(
        output_setting=ShowOutput.NONE, expected_message="demo_test:demo_test succeeded."
    )


def test_streaming_output_failure() -> None:
    assert_failure_streamed = partial(
        assert_streaming_output, exit_code=1, expected_level=LogLevel.ERROR
    )
    message = dedent(
        """\
        demo_test:demo_test failed (exit code 1).
        stdout
        stderr

        """
    )
    assert_failure_streamed(expected_message=message)
    assert_failure_streamed(output_setting=ShowOutput.FAILED, expected_message=message)
    assert_failure_streamed(
        output_setting=ShowOutput.NONE, expected_message="demo_test:demo_test failed (exit code 1)."
    )


def test_runtime_package_dependencies() -> None:
    rule_runner = RuleRunner(
        rules=[
            build_runtime_package_dependencies,
            *pex_from_targets.rules(),
            *package_pex_binary.rules(),
            *python_target_type_rules(),
            QueryRule(BuiltPackageDependencies, [BuildPackageDependenciesRequest]),
        ],
        target_types=[PythonSourcesGeneratorTarget, PexBinary],
    )
    rule_runner.set_options(args=[], env_inherit={"PATH", "PYENV_ROOT", "HOME"})

    rule_runner.write_files(
        {
            "src/py/main.py": "",
            "src/py/BUILD": dedent(
                """\
                python_sources()
                pex_binary(name='main', entry_point='main.py')
                """
            ),
        }
    )
    # Include an irrelevant target that cannot be built with `./pants package`.
    input_field = RuntimePackageDependenciesField(["src/py", "src/py:main"], Address("fake"))
    result = rule_runner.request(
        BuiltPackageDependencies, [BuildPackageDependenciesRequest(input_field)]
    )
    assert len(result) == 1
    built_package = result[0]
    snapshot = rule_runner.request(Snapshot, [built_package.digest])
    assert snapshot.files == ("src.py/main.pex",)


def test_timeout_calculation() -> None:
    def assert_timeout_calculated(
        *,
        field_value: int | None,
        expected: int | None,
        global_default: int | None = None,
        global_max: int | None = None,
        timeouts_enabled: bool = True,
    ) -> None:
        field = MockTestTimeoutField(field_value, Address("", target_name="tests"))
        test_subsystem = create_subsystem(
            TestSubsystem,
            timeouts=timeouts_enabled,
            timeout_default=global_default,
            timeout_maximum=global_max,
        )
        assert field.calculate_from_global_options(test_subsystem) == expected

    assert_timeout_calculated(field_value=10, expected=10)
    assert_timeout_calculated(field_value=20, global_max=10, expected=10)
    assert_timeout_calculated(field_value=None, global_default=20, expected=20)
    assert_timeout_calculated(field_value=None, expected=None)
    assert_timeout_calculated(field_value=None, global_default=20, global_max=10, expected=10)
    assert_timeout_calculated(field_value=10, timeouts_enabled=False, expected=None)
