# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest
from _pytest.monkeypatch import MonkeyPatch

from pants.backend.python.goals import package_pex_binary
from pants.backend.python.target_types import PexBinary, PythonSourcesGeneratorTarget
from pants.backend.python.target_types_rules import rules as python_target_type_rules
from pants.backend.python.util_rules import pex_from_targets
from pants.core.environments.rules import ChosenLocalEnvironmentName
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
    TestDebugRequest,
    TestFieldSet,
    TestRequest,
    TestResult,
    TestSubsystem,
    TestTimeoutField,
    _format_test_rerun_command,
    _format_test_summary,
    build_runtime_package_dependencies,
    run_tests,
)
from pants.core.subsystems.debug_adapter import DebugAdapterSubsystem
from pants.core.util_rules.distdir import DistDir
from pants.core.util_rules.partitions import Partition, Partitions
from pants.engine.addresses import Address
from pants.engine.console import Console
from pants.engine.environment import EnvironmentName
from pants.engine.fs import EMPTY_DIGEST, EMPTY_FILE_DIGEST, FileDigest, Snapshot, Workspace
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
from pants.engine.unions import UnionMembership, UnionRule
from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem
from pants.testutil.option_util import create_goal_subsystem, create_subsystem
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import QueryRule, mock_console, run_rule_with_mocks
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
            execute_in_workspace=False,
            keep_sandboxes="never",
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
        addresses = tuple(field_set.address for field_set in field_sets)
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
    __implicitly: tuple,
) -> Partitions[MockTestFieldSet, Any]:
    request, typ = next(iter(__implicitly[0].items()))
    assert typ == TestRequest.PartitionRequest
    return Partitions(Partition((field_set,), None) for field_set in request.field_sets)


def mock_test_partition(__implicitly: tuple) -> TestResult:
    request, typ = next(iter(__implicitly[0].items()))
    assert typ == TestRequest.Batch
    request_subtype = {cls.Batch: cls for cls in MockTestRequest.__subclasses__()}[type(request)]
    return request_subtype.test_result(request.elements)


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
    experimental_report_test_result_info: bool = False,
    report: bool = False,
    report_dir: str = TestSubsystem.default_report_path,
    output: ShowOutput = ShowOutput.ALL,
    valid_targets: bool = True,
    show_rerun_command: bool = False,
    run_id: RunId = RunId(999),
) -> tuple[int, str]:
    test_subsystem = create_goal_subsystem(
        TestSubsystem,
        debug=debug,
        debug_adapter=False,
        use_coverage=use_coverage,
        experimental_report_test_result_info=experimental_report_test_result_info,
        report=report,
        report_dir=report_dir,
        xml_dir=None,
        output=output,
        extra_env_vars=[],
        shard="",
        batch_size=1,
        show_rerun_command=show_rerun_command,
    )
    debug_adapter_subsystem = create_subsystem(
        DebugAdapterSubsystem,
        host="127.0.0.1",
        port="5678",
    )
    workspace = Workspace(rule_runner.scheduler, _enforce_effects=False)
    union_membership = UnionMembership.from_rules(
        {
            UnionRule(TestFieldSet, MockTestFieldSet),
            UnionRule(TestRequest, request_type),
            UnionRule(TestRequest.PartitionRequest, request_type.PartitionRequest),
            UnionRule(TestRequest.Batch, request_type.Batch),
            UnionRule(CoverageDataCollection, MockCoverageDataCollection),
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
        __implicitly: tuple,
    ) -> TestDebugRequest:
        return TestDebugRequest(InteractiveProcess(["/bin/example"], input_digest=EMPTY_DIGEST))

    def mock_coverage_report_generation(
        __implicitly: tuple,
    ) -> CoverageReports:
        coverage_data_collection, typ = next(iter(__implicitly[0].items()))
        assert typ == CoverageDataCollection
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
            mock_calls={
                "pants.core.goals.test.partition_tests": mock_partitioner,
                "pants.core.environments.rules.resolve_single_environment_name": lambda _a: EnvironmentName(
                    None
                ),
                "pants.core.goals.test.test_batch_to_debug_request": mock_debug_request,
                "pants.core.goals.test.test_batch_to_debug_adapter_request": mock_debug_request,
                "pants.core.goals.test.run_test_batch": mock_test_partition,
                "pants.core.goals.test.create_coverage_report": mock_coverage_report_generation,
                "pants.engine.internals.specs_rules.find_valid_field_sets_for_target_roots": mock_find_valid_field_sets,
                "pants.engine.intrinsics.merge_digests": lambda _: EMPTY_DIGEST,
                "pants.engine.intrinsics._interactive_process": lambda _p,
                _e: InteractiveProcessResult(0),
            },
            union_membership=union_membership,
            # We don't want temporary warnings to interfere with our expected output.
            show_warnings=False,
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


@pytest.mark.parametrize(
    ("show_rerun_command", "expected_stderr"),
    [
        (
            False,
            # the summary is for humans, so we test it literally, to make sure the formatting is good
            dedent(
                """\

                ✓ //:good succeeded in 1.00s (memoized).
                ✕ //:bad failed in 1.00s (memoized).
                """
            ),
        ),
        (
            True,
            dedent(
                """\

                ✓ //:good succeeded in 1.00s (memoized).
                ✕ //:bad failed in 1.00s (memoized).

                To rerun the failing tests, use:

                    pants test //:bad
                """
            ),
        ),
    ],
)
def test_summary(
    rule_runner: PythonRuleRunner, show_rerun_command: bool, expected_stderr: str
) -> None:
    good_address = Address("", target_name="good")
    bad_address = Address("", target_name="bad")
    skipped_address = Address("", target_name="skipped")

    exit_code, stderr = run_test_rule(
        rule_runner,
        request_type=ConditionallySucceedsRequest,
        targets=[make_target(good_address), make_target(bad_address), make_target(skipped_address)],
        show_rerun_command=show_rerun_command,
    )
    assert exit_code == ConditionallySucceedsRequest.exit_code((bad_address,))
    assert stderr == expected_stderr


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


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        pytest.param([], None, id="no_results"),
        pytest.param(
            [make_test_result([Address("", target_name="t1")], exit_code=0)], None, id="one_success"
        ),
        pytest.param(
            [make_test_result([Address("", target_name="t2")], exit_code=None)],
            None,
            id="one_no_run",
        ),
        pytest.param(
            [make_test_result([Address("", target_name="t3")], exit_code=1)],
            "To rerun the failing tests, use:\n\n    pants test //:t3",
            id="one_failure",
        ),
        pytest.param(
            [
                make_test_result([Address("", target_name="t1")], exit_code=0),
                make_test_result([Address("", target_name="t2")], exit_code=None),
                make_test_result([Address("", target_name="t3")], exit_code=1),
            ],
            "To rerun the failing tests, use:\n\n    pants test //:t3",
            id="one_of_each",
        ),
        pytest.param(
            [
                make_test_result([Address("path/to", target_name="t1")], exit_code=1),
                make_test_result([Address("another/path", target_name="t2")], exit_code=2),
                make_test_result([Address("", target_name="t3")], exit_code=3),
            ],
            "To rerun the failing tests, use:\n\n    pants test //:t3 another/path:t2 path/to:t1",
            id="multiple_failures",
        ),
        pytest.param(
            [
                make_test_result(
                    [
                        Address(
                            "path with spaces",
                            target_name="$*",
                            parameters=dict(key="value"),
                            generated_name="gn",
                        )
                    ],
                    exit_code=1,
                )
            ],
            "To rerun the failing tests, use:\n\n    pants test 'path with spaces:$*#gn@key=value'",
            id="special_characters_require_quoting",
        ),
    ],
)
def test_format_rerun_command(results: list[TestResult], expected: None | str) -> None:
    assert expected == _format_test_rerun_command(results)


def test_debug_target(rule_runner: PythonRuleRunner, monkeypatch: MonkeyPatch) -> None:
    def noop():
        pass

    monkeypatch.setattr("pants.engine.intrinsics.task_side_effected", noop)
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
    def create_test_result(exit_code: int | None, addresses: Iterable[Address]) -> TestResult:
        return TestResult(
            exit_code=exit_code,
            addresses=tuple(addresses),
            stdout_bytes=b"",
            stdout_digest=EMPTY_FILE_DIGEST,
            stderr_bytes=b"",
            stderr_digest=EMPTY_FILE_DIGEST,
            output_setting=ShowOutput.ALL,
            result_metadata=None,
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
        stdout_bytes=b"\x80\xbf",  # invalid UTF-8 as required by the test
        stderr_bytes=b"\x80\xbf",  # invalid UTF-8 as required by the test
        output_setting=ShowOutput.ALL,
    )
    assert test_result.message() == "failed (exit code 1).\n��\n��\n\n"
