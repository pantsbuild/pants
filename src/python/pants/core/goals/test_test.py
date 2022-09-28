# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from textwrap import dedent
from typing import Iterable, Sequence, Type

import pytest

from pants.backend.python.goals import package_pex_binary
from pants.backend.python.target_types import PexBinary, PythonSourcesGeneratorTarget
from pants.backend.python.target_types_rules import rules as python_target_type_rules
from pants.backend.python.util_rules import pex_from_targets
from pants.base.specs import Specs
from pants.core.goals.test import (
    BuildPackageDependenciesRequest,
    BuiltPackageDependencies,
    ConsoleCoverageReport,
    CoverageData,
    CoverageDataCollection,
    CoverageReports,
    Partitions,
    RuntimePackageDependenciesField,
    ShowOutput,
    Test,
    TestDebugAdapterRequest,
    TestDebugRequest,
    TestFieldSet,
    TestRequest,
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
from pants.engine.target import BoolField, FilteredTargets, MultipleSourcesField, Target
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


class MockSkipTestsField(BoolField):
    alias = "skip_mock_test"
    default = False


class MockTarget(Target):
    alias = "mock_target"
    core_fields = (MockMultipleSourcesField, MockSkipTestsField)


@dataclass(frozen=True)
class MockCoverageData(CoverageData):
    addresses: Iterable[Address]


class MockCoverageDataCollection(CoverageDataCollection):
    element_type = MockCoverageData


class MockTestFieldSet(TestFieldSet, metaclass=ABCMeta):
    required_fields = (MultipleSourcesField,)

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(MockSkipTestsField).value


class MockTestRequest(TestRequest):
    field_set_type = MockTestFieldSet

    @staticmethod
    @abstractmethod
    def exit_code(_: Iterable[Address]) -> int:
        pass

    @staticmethod
    @abstractmethod
    def skipped(_: Iterable[Address]) -> bool:
        pass

    @classmethod
    def test_result(cls, partition: str, field_sets: Iterable[MockTestFieldSet]) -> TestResult:
        addresses = [field_set.address for field_set in field_sets]
        return TestResult(
            exit_code=cls.exit_code(addresses),
            stdout="",
            stdout_digest=EMPTY_FILE_DIGEST,
            stderr="",
            stderr_digest=EMPTY_FILE_DIGEST,
            coverage_data=MockCoverageData(addresses),
            output_setting=ShowOutput.ALL,
            result_metadata=None
            if cls.skipped(addresses)
            else ProcessResultMetadata(999, "ran_locally", 0),
            partition_description=partition,
        )


class SuccessfulRequest(MockTestRequest):
    name = "SuccessfulTest"

    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return 0

    @staticmethod
    def skipped(_: Iterable[Address]) -> bool:
        return False


class ConditionallySucceedsRequest(MockTestRequest):
    name = "ConditionallySucceedsTest"

    @staticmethod
    def exit_code(addresses: Iterable[Address]) -> int:
        if any(address.target_name == "bad" for address in addresses):
            return 127
        return 0

    @staticmethod
    def skipped(addresses: Iterable[Address]) -> bool:
        return any(address.target_name == "skipped" for address in addresses)


def mock_partitioner(
    request: MockTestRequest.PartitionRequest,
) -> Partitions[MockTestFieldSet]:
    return Partitions.partition_per_input(request.field_sets)


def mock_test_partition(request: MockTestRequest.SubPartition) -> TestResult:
    request_type = {cls.SubPartition: cls for cls in MockTestRequest.__subclasses__()}[
        type(request)
    ]
    return request_type.test_result(request.key, request.elements)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner()


def make_target(address: Address | None = None, *, skip: bool = False) -> Target:
    if address is None:
        address = Address("", target_name="tests")
    return MockTarget({MockSkipTestsField.alias: skip}, address)


def run_test_rule(
    rule_runner: RuleRunner,
    *,
    request_types: Sequence[Type[TestRequest]],
    targets: list[Target],
    debug: bool = False,
    use_coverage: bool = False,
    report: bool = False,
    report_dir: str = TestSubsystem.default_report_path,
    output: ShowOutput = ShowOutput.ALL,
    run_id: RunId = RunId(999),
    batch_size: int = 128,
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
        batch_size=batch_size,
    )
    debug_adapter_subsystem = create_subsystem(
        DebugAdapterSubsystem,
        host="127.0.0.1",
        port="5678",
    )
    workspace = Workspace(rule_runner.scheduler, _enforce_effects=False)
    union_membership = UnionMembership(
        {
            TestRequest: list(request_types),
            TestRequest.SubPartition: [rt.SubPartition for rt in request_types],
            TestRequest.PartitionRequest: [rt.PartitionRequest for rt in request_types],
            CoverageDataCollection: [MockCoverageDataCollection],
        }
    )

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
            address.spec
            for coverage_data in coverage_data_collection
            for address in coverage_data.addresses
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
                Specs.empty(),
            ],
            mock_gets=[
                MockGet(
                    output_type=Partitions,
                    input_types=(TestRequest.PartitionRequest,),
                    mock=mock_partitioner,
                ),
                MockGet(
                    output_type=TestResult,
                    input_types=(TestRequest.SubPartition,),
                    mock=mock_test_partition,
                ),
                MockGet(
                    output_type=TestDebugRequest,
                    input_types=(TestRequest.SubPartition,),
                    mock=mock_debug_request,
                ),
                MockGet(
                    output_type=TestDebugAdapterRequest,
                    input_types=(TestRequest.SubPartition,),
                    mock=mock_debug_adapter_request,
                ),
                MockGet(
                    output_type=FilteredTargets,
                    input_types=(Specs,),
                    mock=lambda _: FilteredTargets(tuple(targets)),
                ),
                # Merge XML results.
                MockGet(
                    output_type=Digest,
                    input_types=(MergeDigests,),
                    mock=lambda _: EMPTY_DIGEST,
                ),
                MockGet(
                    output_type=CoverageReports,
                    input_types=(CoverageDataCollection,),
                    mock=mock_coverage_report_generation,
                ),
                MockGet(
                    output_type=OpenFiles,
                    input_types=(OpenFilesRequest,),
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


def test_skipped_target_noops(rule_runner: RuleRunner) -> None:
    exit_code, stderr = run_test_rule(
        rule_runner,
        request_types=[SuccessfulRequest],
        targets=[make_target(skip=True)],
    )
    assert exit_code == 0
    assert stderr.strip() == ""


def test_summary(rule_runner: RuleRunner) -> None:
    good_address = Address("", target_name="good")
    bad_address = Address("", target_name="bad")
    skipped_address = Address("", target_name="skipped")

    exit_code, stderr = run_test_rule(
        rule_runner,
        request_types=[ConditionallySucceedsRequest],
        targets=[make_target(good_address), make_target(bad_address), make_target(skipped_address)],
    )
    assert exit_code == ConditionallySucceedsRequest.exit_code([bad_address])
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
            partition_description="//:dummy_address",
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
        request_types=[SuccessfulRequest],
        targets=[make_target()],
        debug=True,
    )
    assert exit_code == 0


def test_report(rule_runner: RuleRunner) -> None:
    addr1 = Address("", target_name="t1")
    addr2 = Address("", target_name="t2")
    exit_code, stderr = run_test_rule(
        rule_runner,
        request_types=[SuccessfulRequest],
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
        request_types=[SuccessfulRequest],
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
        request_types=[SuccessfulRequest],
        targets=[make_target(addr1), make_target(addr2)],
        use_coverage=True,
    )
    assert exit_code == 0
    assert stderr.strip().endswith(f"Ran coverage on {addr1.spec}, {addr2.spec}")


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
        result_metadata=result_metadata,
        partition_description="demo_test",
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
        output_setting=ShowOutput.FAILED,
        expected_message="demo_test succeeded.",
    )
    assert_success_streamed(
        output_setting=ShowOutput.NONE,
        expected_message="demo_test succeeded.",
    )


def test_streaming_output_failure() -> None:
    assert_failure_streamed = partial(
        assert_streaming_output, exit_code=1, expected_level=LogLevel.ERROR
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
        output_setting=ShowOutput.NONE,
        expected_message="demo_test failed (exit code 1).",
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
