# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Any, Iterable

import pytest

from pants.core.goals.bench import (
    Benchmark,
    BenchmarkFieldSet,
    BenchmarkRequest,
    BenchmarkResult,
    BenchmarkSubsystem,
    BenchmarkTimeoutField,
    ShowOutput,
    run_bench,
)
from pants.core.util_rules.distdir import DistDir
from pants.core.util_rules.environments import SingleEnvironmentNameRequest
from pants.core.util_rules.partitions import Partition, Partitions
from pants.engine.addresses import Address
from pants.engine.environment import ChosenLocalEnvironmentName, EnvironmentName
from pants.engine.fs import EMPTY_DIGEST, EMPTY_FILE_DIGEST, Digest, MergeDigests, Workspace
from pants.engine.internals.session import RunId
from pants.engine.platform import Platform
from pants.engine.process import ProcessExecutionEnvironment, ProcessResultMetadata
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
from pants.testutil.rule_runner import MockGet, RuleRunner, mock_console, run_rule_with_mocks


class MockMultipleSourcesField(MultipleSourcesField):
    pass


class MockBenchTimeoutField(BenchmarkTimeoutField):
    pass


class MockSkipBenchesField(BoolField):
    alias = "skip_bench"
    default = False


class MockRequiredField(Field):
    alias = "required"
    required = True


class MockTarget(Target):
    alias = "mock_target"
    core_fields = (
        MockMultipleSourcesField,
        MockRequiredField,
        MockSkipBenchesField,
        MockBenchTimeoutField,
    )


@dataclass(frozen=True)
class MockBenchFieldSet(BenchmarkFieldSet):
    required_fields = (MockMultipleSourcesField, MockRequiredField)

    sources: MockMultipleSourcesField
    required: MockRequiredField
    timeout: MockBenchTimeoutField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(MockSkipBenchesField).value


class MockBenchSubsystem(Subsystem):
    options_scope = "mock-bench"
    help = "Not real bench"
    name = "MockBench"
    skip = SkipOption("bench")


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


class MockBenchRequest(BenchmarkRequest):
    field_set_type = MockBenchFieldSet
    tool_subsystem = MockBenchSubsystem

    @staticmethod
    @abstractmethod
    def exit_code(_: Iterable[Address]) -> int:
        pass

    @staticmethod
    @abstractmethod
    def skipped(_: Iterable[Address]) -> bool:
        pass

    @classmethod
    def bench_result(cls, field_sets: Iterable[MockBenchFieldSet]) -> BenchmarkResult:
        addresses = [field_set.address for field_set in field_sets]
        return BenchmarkResult(
            exit_code=cls.exit_code(addresses),
            stdout="",
            stdout_digest=EMPTY_FILE_DIGEST,
            stderr="",
            stderr_digest=EMPTY_FILE_DIGEST,
            addresses=tuple(addresses),
            output_setting=ShowOutput.ALL,
            result_metadata=None if cls.skipped(addresses) else make_process_result_metadata("ran"),
        )


class SuccessfulRequest(MockBenchRequest):
    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return 0

    @staticmethod
    def skipped(_: Iterable[Address]) -> bool:
        return False


class ConditionallySucceedsRequest(MockBenchRequest):
    @staticmethod
    def exit_code(addresses: Iterable[Address]) -> int:
        if any(address.target_name == "bad" for address in addresses):
            return 27
        return 0

    @staticmethod
    def skipped(addresses: Iterable[Address]) -> bool:
        return any(address.target_name == "skipped" for address in addresses)


def mock_partitioner(
    request: MockBenchRequest.PartitionRequest,
    _: EnvironmentName,
) -> Partitions[MockBenchFieldSet, Any]:
    return Partitions(Partition((field_set,), None) for field_set in request.field_sets)


def mock_bench_partition(request: MockBenchRequest.Batch, _: EnvironmentName) -> BenchmarkResult:
    request_type = {cls.Batch: cls for cls in MockBenchRequest.__subclasses__()}[type(request)]
    return request_type.bench_result(request.elements)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner()


def make_target(address: Address | None = None, *, skip: bool = False) -> Target:
    if address is None:
        address = Address("", target_name="benches")
    return MockTarget(
        {MockSkipBenchesField.alias: skip, MockRequiredField.alias: "present"}, address
    )


def run_bench_goal(
    rule_runner: RuleRunner,
    *,
    request_type: type[BenchmarkRequest],
    targets: list[Target],
    report: bool = False,
    report_dir: str = BenchmarkSubsystem.default_report_path,
    output: ShowOutput = ShowOutput.ALL,
    valid_targets: bool = True,
    run_id: RunId = RunId(999),
) -> tuple[int, str]:
    bench_subsystem = create_goal_subsystem(
        BenchmarkSubsystem,
        report=report,
        report_dir=report_dir,
        output=output,
        extra_env_vars=[],
        shard="",
        batch_size=1,
    )
    workspace = Workspace(rule_runner.scheduler, _enforce_effects=False)
    union_membership = UnionMembership(
        {
            BenchmarkFieldSet: [MockBenchFieldSet],
            BenchmarkRequest: [request_type],
            BenchmarkRequest.PartitionRequest: [request_type.PartitionRequest],
            BenchmarkRequest.Batch: [request_type.Batch],
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

    with mock_console(rule_runner.options_bootstrapper) as (console, stdio_reader):
        result: Benchmark = run_rule_with_mocks(
            run_bench,
            rule_args=[
                console,
                workspace,
                DistDir(relpath=Path("dist")),
                bench_subsystem,
                ChosenLocalEnvironmentName(EnvironmentName(None)),
                union_membership,
                run_id,
            ],
            mock_gets=[
                MockGet(
                    output_type=TargetRootsToFieldSets,
                    input_types=(TargetRootsToFieldSetsRequest,),
                    mock=mock_find_valid_field_sets,
                ),
                MockGet(
                    output_type=Partitions,
                    input_types=(BenchmarkRequest.PartitionRequest, EnvironmentName),
                    mock=mock_partitioner,
                ),
                MockGet(
                    output_type=EnvironmentName,
                    input_types=(SingleEnvironmentNameRequest,),
                    mock=lambda _a: EnvironmentName(None),
                ),
                MockGet(
                    output_type=BenchmarkResult,
                    input_types=(BenchmarkRequest.Batch, EnvironmentName),
                    mock=mock_bench_partition,
                ),
                MockGet(
                    output_type=Digest,
                    input_types=(MergeDigests,),
                    mock=lambda _: EMPTY_DIGEST,
                ),
            ],
            union_membership=union_membership,
        )
        assert not stdio_reader.get_stdout(), stdio_reader.get_stdout()
        return result.exit_code, stdio_reader.get_stderr()


def test_invalid_target_noops(rule_runner: RuleRunner) -> None:
    exit_code, stderr = run_bench_goal(
        rule_runner,
        request_type=SuccessfulRequest,
        targets=[make_target()],
        valid_targets=False,
    )
    assert exit_code == 0
    assert stderr.strip() == ""


def test_skipped_target_noops(rule_runner: RuleRunner) -> None:
    exit_code, stderr = run_bench_goal(
        rule_runner,
        request_type=ConditionallySucceedsRequest,
        targets=[make_target(Address("", target_name="bad"), skip=True)],
    )
    assert exit_code == 0
    assert stderr.strip() == ""


def test_summary(rule_runner: RuleRunner) -> None:
    good_address = Address("", target_name="good")
    bad_address = Address("", target_name="bad")
    skipped_address = Address("", target_name="skipped")

    exit_code, stderr = run_bench_goal(
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


def test_report(rule_runner: RuleRunner) -> None:
    addr1 = Address("", target_name="t1")
    addr2 = Address("", target_name="t2")
    exit_code, stderr = run_bench_goal(
        rule_runner,
        request_type=SuccessfulRequest,
        targets=[make_target(addr1), make_target(addr2)],
        report=True,
    )
    assert exit_code == 0
    assert "Wrote benchmark reports to dist/bench/reports" in stderr


def test_report_dir(rule_runner: RuleRunner) -> None:
    report_dir = "dist/bench-results"
    addr1 = Address("", target_name="t1")
    addr2 = Address("", target_name="t2")
    exit_code, stderr = run_bench_goal(
        rule_runner,
        request_type=SuccessfulRequest,
        targets=[make_target(addr1), make_target(addr2)],
        report=True,
        report_dir=report_dir,
    )
    assert exit_code == 0
    assert f"Wrote benchmark reports to {report_dir}" in stderr


def test_timeout_calculation() -> None:
    def assert_timeout_calculated(
        *,
        field_value: int | None,
        expected: int | None,
        global_default: int | None = None,
        global_max: int | None = None,
        timeouts_enabled: bool = True,
    ) -> None:
        field = MockBenchTimeoutField(field_value, Address("", target_name="benches"))
        test_subsystem = create_subsystem(
            BenchmarkSubsystem,
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
