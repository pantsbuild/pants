# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from textwrap import dedent
from typing import Any, Iterable

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
from pants.core.util_rules.environments import (
    ChosenLocalEnvironmentName,
    SingleEnvironmentNameRequest,
)
from pants.core.util_rules.partitions import Partition, Partitions
from pants.engine.addresses import Address
from pants.engine.console import Console
from pants.engine.desktop import OpenFiles, OpenFilesRequest
from pants.engine.environment import EnvironmentName
from pants.engine.fs import (
    EMPTY_DIGEST,
    EMPTY_FILE_DIGEST,
    Digest,
    FileDigest,
    MergeDigests,
    Snapshot,
    Workspace,
)
from pants.engine.internals.session import RunId
from pants.engine.platform import Platform
from pants.engine.process import (
    InteractiveProcess,
    InteractiveProcessResult,
    ProcessExecutionEnvironment,
    ProcessResultMetadata,
)
from pants.engine.target import (
    BoolField,
    Field,
    MultipleSourcesField,
    Target,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
)
from pants.engine.unions import UnionMembership
from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem
from pants.testutil.option_util import create_goal_subsystem, create_subsystem
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import (
    MockEffect,
    MockGet,
    QueryRule,
    mock_console,
    run_rule_with_mocks,
)
from pants.util.logging import LogLevel


def make_process_result_metadata(
    source: str,
    *,
    environment_name: str | None = None,
    docker_image: str | None = None,
    remote_execution: bool = False,
    total_elapsed_ms: int = 999,
    source_run_id: int = 0,
) -> ProcessResultMetadata:
    return ProcessResultMetadata(
        total_elapsed_ms,
        ProcessExecutionEnvironment(
            environment_name=environment_name,
            # TODO: None of the following are currently consumed in these tests.
            platform=Platform.create_for_localhost().value,
            docker_image=docker_image,
            remote_execution=remote_execution,
            remote_execution_extra_platform_properties=[],
        ),
        source,
        source_run_id,
    )


def make_test_result(
    addresses: Iterable[Address],
    exit_code: None | int,
    stdout_bytes: bytes = b"",
    stdout_digest: FileDigest = EMPTY_FILE_DIGEST,
    stderr_bytes: bytes = b"",
    stderr_digest: FileDigest = EMPTY_FILE_DIGEST,
    coverage_data: CoverageData | None = None,
    output_setting: ShowOutput = ShowOutput.NONE,
    result_metadata: None | ProcessResultMetadata = None,
) -> TestResult:
    """Create a TestResult with default values for most fields."""
    return TestResult(
        addresses=tuple(addresses),
        exit_code=exit_code,
        stdout_bytes=stdout_bytes,
        stdout_digest=stdout_digest,
        stderr_bytes=stderr_bytes,
        stderr_digest=stderr_digest,
        coverage_data=coverage_data,
        output_setting=output_setting,
        result_metadata=result_metadata,
    )


class MockMultipleSourcesField(MultipleSourcesField):
    pass


class MockTestTimeoutField(TestTimeoutField):
    pass


class MockSkipTestsField(BoolField):
    alias = "skip_test"
    default = False


class MockRequiredField(Field):
    alias = "required"
    required = True


class MockTarget(Target):
    alias = "mock_target"
    core_fields = (MockMultipleSourcesField, MockSkipTestsField, MockRequiredField)


@dataclass(frozen=True)
class MockCoverageData(CoverageData):
    addresses: Iterable[Address]


class MockCoverageDataCollection(CoverageDataCollection):
    element_type = MockCoverageData


@dataclass(frozen=True)
class MockTestFieldSet(TestFieldSet):
    required_fields = (MultipleSourcesField, MockRequiredField)
    sources: MultipleSourcesField
    required: MockRequiredField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(MockSkipTestsField).value


class MockTestSubsystem(Subsystem):
    options_scope = "mock-test"
    help = "Not real"
    name = "Mock"
    skip = SkipOption("test")


class MockTestRequest(TestRequest):
    field_set_type = MockTestFieldSet
    tool_subsystem = MockTestSubsystem

    @staticmethod
    @abstractmethod
    def exit_code(_: Iterable[Address]) -> int:
        pass

    @staticmethod
    @abstractmethod
    def skipped(_: Iterable[Address]) -> bool:
        pass

    @classmethod
    def test_result(cls, field_sets: Iterable[MockTestFieldSet]) -> TestResult:
        addresses = [field_set.address for field_set in field_sets]
        return make_test_result(
            addresses,
            exit_code=cls.exit_code(addresses),
            coverage_data=MockCoverageData(addresses),
            output_setting=ShowOutput.ALL,
            result_metadata=None if cls.skipped(addresses) else make_process_result_metadata("ran"),
        )


class SuccessfulRequest(MockTestRequest):
    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return 0

    @staticmethod
    def skipped(_: Iterable[Address]) -> bool:
        return False


class ConditionallySucceedsRequest(MockTestRequest):
    @staticmethod
    def exit_code(addresses: Iterable[Address]) -> int:
        if any(address.target_name == "bad" for address in addresses):
            return 27
        return 0

    @staticmethod
    def skipped(addresses: Iterable[Address]) -> bool:
        return any(address.target_name == "skipped" for address in addresses)


def mock_partitioner(
    request: MockTestRequest.PartitionRequest,
    _: EnvironmentName,
) -> Partitions[MockTestFieldSet, Any]:
    return Partitions(Partition((field_set,), None) for field_set in request.field_sets)


def mock_test_partition(request: MockTestRequest.Batch, _: EnvironmentName) -> TestResult:
    request_type = {cls.Batch: cls for cls in MockTestRequest.__subclasses__()}[type(request)]
    return request_type.test_result(request.elements)


@pytest.fixture
def rule_runner() -> PythonRuleRunner:
    return PythonRuleRunner()


def make_target(address: Address | None = None, *, skip: bool = False) -> Target:
    if address is None:
        address = Address("", target_name="tests")
    return MockTarget({MockSkipTestsField.alias: skip, MockRequiredField.alias: "present"}, address)


def run_test_rule(
    rule_runner: PythonRuleRunner,
    *,
    request_type: type[TestRequest],
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
        batch_size=1,
    )
    debug_adapter_subsystem = create_subsystem(
        DebugAdapterSubsystem,
        host="127.0.0.1",
        port="5678",
    )
    workspace = Workspace(rule_runner.scheduler, _enforce_effects=False)
    union_membership = UnionMembership(
        {
            TestFieldSet: [MockTestFieldSet],
            TestRequest: [request_type],
            TestRequest.PartitionRequest: [request_type.PartitionRequest],
            TestRequest.Batch: [request_type.Batch],
            CoverageDataCollection: [MockCoverageDataCollection],
        }
    )

    def mock_find_valid_field_sets(
        _: TargetRootsToFieldSetsRequest,
    ) -> TargetRootsToFieldSets:
        if not valid_targets:
            return TargetRootsToFieldSets({})
        return TargetRootsToFieldSets(
            {
                tgt: [request_type.field_set_type.create(tgt)]
                for tgt in targets
                if request_type.field_set_type.is_applicable(tgt)
            }
        )

    def mock_debug_request(
        _field_set: TestFieldSet, _environment_name: EnvironmentName
    ) -> TestDebugRequest:
        return TestDebugRequest(InteractiveProcess(["/bin/example"], input_digest=EMPTY_DIGEST))

    def mock_debug_adapter_request(_: TestFieldSet) -> TestDebugAdapterRequest:
        return TestDebugAdapterRequest(
            InteractiveProcess(["/bin/example"], input_digest=EMPTY_DIGEST)
        )

    def mock_coverage_report_generation(
        coverage_data_collection: MockCoverageDataCollection,
        _: EnvironmentName,
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
                ChosenLocalEnvironmentName(EnvironmentName(None)),
            ],
            mock_gets=[
                MockGet(
                    output_type=TargetRootsToFieldSets,
                    input_types=(TargetRootsToFieldSetsRequest,),
                    mock=mock_find_valid_field_sets,
                ),
                MockGet(
                    output_type=Partitions,
                    input_types=(TestRequest.PartitionRequest, EnvironmentName),
                    mock=mock_partitioner,
                ),
                MockGet(
                    output_type=EnvironmentName,
                    input_types=(SingleEnvironmentNameRequest,),
                    mock=lambda _a: EnvironmentName(None),
                ),
                MockGet(
                    output_type=TestResult,
                    input_types=(TestRequest.Batch, EnvironmentName),
                    mock=mock_test_partition,
                ),
                MockGet(
                    output_type=TestDebugRequest,
                    input_types=(TestRequest.Batch, EnvironmentName),
                    mock=mock_debug_request,
                ),
                MockGet(
                    output_type=TestDebugAdapterRequest,
                    input_types=(TestFieldSet,),
                    mock=mock_debug_adapter_request,
                ),
                # Merge XML results.
                MockGet(
                    output_type=Digest,
                    input_types=(MergeDigests,),
                    mock=lambda _: EMPTY_DIGEST,
                ),
                MockGet(
                    output_type=CoverageReports,
                    input_types=(CoverageDataCollection, EnvironmentName),
                    mock=mock_coverage_report_generation,
                ),
                MockGet(
                    output_type=OpenFiles,
                    input_types=(OpenFilesRequest,),
                    mock=lambda _: OpenFiles(()),
                ),
                MockEffect(
                    output_type=InteractiveProcessResult,
                    input_types=(InteractiveProcess, EnvironmentName),
                    mock=lambda _p, _e: InteractiveProcessResult(0),
                ),
            ],
            union_membership=union_membership,
        )
        assert not stdio_reader.get_stdout()
        return result.exit_code, stdio_reader.get_stderr()


def test_invalid_target_noops(rule_runner: PythonRuleRunner) -> None:
    exit_code, stderr = run_test_rule(
        rule_runner,
        request_type=SuccessfulRequest,
        targets=[make_target()],
        valid_targets=False,
    )
    assert exit_code == 0
    assert stderr.strip() == ""


def test_skipped_target_noops(rule_runner: PythonRuleRunner) -> None:
    exit_code, stderr = run_test_rule(
        rule_runner,
        request_type=ConditionallySucceedsRequest,
        targets=[make_target(Address("", target_name="bad"), skip=True)],
    )
    assert exit_code == 0
    assert stderr.strip() == ""


def test_summary(rule_runner: PythonRuleRunner) -> None:
    good_address = Address("", target_name="good")
    bad_address = Address("", target_name="bad")
    skipped_address = Address("", target_name="skipped")

    exit_code, stderr = run_test_rule(
        rule_runner,
        request_type=ConditionallySucceedsRequest,
        targets=[make_target(good_address), make_target(bad_address), make_target(skipped_address)],
    )
    assert exit_code == ConditionallySucceedsRequest.exit_code((bad_address,))
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
        make_test_result(
            [Address(spec_path="", target_name="dummy_address")],
            exit_code=exit_code,
            result_metadata=result_metadata,
            output_setting=ShowOutput.FAILED,
        ),
        RunId(run_id),
        Console(use_colors=False),
    )


def test_format_summary_remote(rule_runner: PythonRuleRunner) -> None:
    _assert_test_summary(
        "✓ //:dummy_address succeeded in 0.05s (ran in remote environment `ubuntu`).",
        exit_code=0,
        run_id=0,
        result_metadata=make_process_result_metadata(
            "ran", environment_name="ubuntu", remote_execution=True, total_elapsed_ms=50
        ),
    )


def test_format_summary_local(rule_runner: PythonRuleRunner) -> None:
    _assert_test_summary(
        "✓ //:dummy_address succeeded in 0.05s.",
        exit_code=0,
        run_id=0,
        result_metadata=make_process_result_metadata(
            "ran", environment_name=None, total_elapsed_ms=50
        ),
    )


def test_format_summary_memoized(rule_runner: PythonRuleRunner) -> None:
    _assert_test_summary(
        "✓ //:dummy_address succeeded in 0.05s (memoized).",
        exit_code=0,
        run_id=1234,
        result_metadata=make_process_result_metadata("ran", total_elapsed_ms=50),
    )


def test_format_summary_memoized_remote(rule_runner: PythonRuleRunner) -> None:
    _assert_test_summary(
        "✓ //:dummy_address succeeded in 0.05s (memoized for remote environment `ubuntu`).",
        exit_code=0,
        run_id=1234,
        result_metadata=make_process_result_metadata(
            "ran", environment_name="ubuntu", remote_execution=True, total_elapsed_ms=50
        ),
    )


def test_debug_target(rule_runner: PythonRuleRunner) -> None:
    exit_code, _ = run_test_rule(
        rule_runner,
        request_type=SuccessfulRequest,
        targets=[make_target()],
        debug=True,
    )
    assert exit_code == 0


def test_report(rule_runner: PythonRuleRunner) -> None:
    addr1 = Address("", target_name="t1")
    addr2 = Address("", target_name="t2")
    exit_code, stderr = run_test_rule(
        rule_runner,
        request_type=SuccessfulRequest,
        targets=[make_target(addr1), make_target(addr2)],
        report=True,
    )
    assert exit_code == 0
    assert "Wrote test reports to dist/test/reports" in stderr


def test_report_dir(rule_runner: PythonRuleRunner) -> None:
    report_dir = "dist/test-results"
    addr1 = Address("", target_name="t1")
    addr2 = Address("", target_name="t2")
    exit_code, stderr = run_test_rule(
        rule_runner,
        request_type=SuccessfulRequest,
        targets=[make_target(addr1), make_target(addr2)],
        report=True,
        report_dir=report_dir,
    )
    assert exit_code == 0
    assert f"Wrote test reports to {report_dir}" in stderr


def test_coverage(rule_runner: PythonRuleRunner) -> None:
    addr1 = Address("", target_name="t1")
    addr2 = Address("", target_name="t2")
    exit_code, stderr = run_test_rule(
        rule_runner,
        request_type=SuccessfulRequest,
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
    skip1 = create_test_result(
        exit_code=None,
        addresses=(Address("t1"),),
    )
    skip2 = create_test_result(
        exit_code=None,
        addresses=(Address("t2"),),
    )
    success1 = create_test_result(
        exit_code=0,
        addresses=(Address("t1"),),
    )
    success2 = create_test_result(
        exit_code=0,
        addresses=(Address("t2"),),
    )
    fail1 = create_test_result(
        exit_code=1,
        addresses=(Address("t1"),),
    )
    fail2 = create_test_result(
        exit_code=1,
        addresses=(Address("t2"),),
    )
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
    result_metadata: ProcessResultMetadata = make_process_result_metadata("dummy"),
) -> None:
    result = make_test_result(
        addresses=(Address("demo_test"),),
        exit_code=exit_code,
        stdout_bytes=stdout.encode(),
        stderr_bytes=stderr.encode(),
        output_setting=output_setting,
        result_metadata=result_metadata,
    )
    assert result.level() == expected_level
    assert result.message() == expected_message


def test_streaming_output_no_tests() -> None:
    assert_streaming_output(
        exit_code=None,
        stdout="",
        stderr="",
        expected_level=LogLevel.DEBUG,
        expected_message="no tests found.",
    )


def test_streaming_output_success() -> None:
    assert_success_streamed = partial(
        assert_streaming_output, exit_code=0, expected_level=LogLevel.INFO
    )
    assert_success_streamed(
        expected_message=dedent(
            """\
            succeeded.
            stdout
            stderr

            """
        ),
    )
    assert_success_streamed(output_setting=ShowOutput.FAILED, expected_message="succeeded.")
    assert_success_streamed(output_setting=ShowOutput.NONE, expected_message="succeeded.")


def test_streaming_output_failure() -> None:
    assert_failure_streamed = partial(
        assert_streaming_output, exit_code=1, expected_level=LogLevel.ERROR
    )
    message = dedent(
        """\
        failed (exit code 1).
        stdout
        stderr

        """
    )
    assert_failure_streamed(expected_message=message)
    assert_failure_streamed(output_setting=ShowOutput.FAILED, expected_message=message)
    assert_failure_streamed(
        output_setting=ShowOutput.NONE, expected_message="failed (exit code 1)."
    )


def test_runtime_package_dependencies() -> None:
    rule_runner = PythonRuleRunner(
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


def test_non_utf8_output() -> None:
    test_result = make_test_result(
        [],
        exit_code=1,  # "test error" so stdout/stderr are output in message
        stdout_bytes=b"\x80\xBF",  # invalid UTF-8 as required by the test
        stderr_bytes=b"\x80\xBF",  # invalid UTF-8 as required by the test
        output_setting=ShowOutput.ALL,
    )
    assert test_result.message() == "failed (exit code 1).\n��\n��\n\n"
