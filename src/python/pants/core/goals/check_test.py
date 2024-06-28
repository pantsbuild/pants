# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from pathlib import Path
from textwrap import dedent
from typing import Iterable, Optional, Sequence, Tuple, Type

import pytest

from pants.core.goals.check import (
    Check,
    CheckRequest,
    CheckResult,
    CheckResults,
    CheckSubsystem,
    check,
)
from pants.core.util_rules.distdir import DistDir
from pants.core.util_rules.environments import EnvironmentNameRequest
from pants.engine.addresses import Address
from pants.engine.environment import EnvironmentName
from pants.engine.fs import EMPTY_DIGEST, EMPTY_FILE_DIGEST, Workspace
from pants.engine.platform import Platform
from pants.engine.process import (
    FallibleProcessResult,
    ProcessExecutionEnvironment,
    ProcessResultMetadata,
)
from pants.engine.target import FieldSet, MultipleSourcesField, Target, Targets
from pants.engine.unions import UnionMembership
from pants.testutil.option_util import create_options_bootstrapper, create_subsystem
from pants.testutil.rule_runner import MockGet, RuleRunner, mock_console, run_rule_with_mocks
from pants.util.logging import LogLevel
from pants.util.meta import classproperty
from pants.util.strutil import Simplifier


class MockMultipleSourcesField(MultipleSourcesField):
    pass


class MockTarget(Target):
    alias = "mock_target"
    core_fields = (MockMultipleSourcesField,)


class MockCheckFieldSet(FieldSet):
    required_fields = (MultipleSourcesField,)


class MockCheckRequest(CheckRequest, metaclass=ABCMeta):
    field_set_type = MockCheckFieldSet

    @staticmethod
    @abstractmethod
    def exit_code(_: Iterable[Address]) -> int:
        pass

    @property
    def check_results(self) -> CheckResults:
        addresses = [config.address for config in self.field_sets]
        return CheckResults(
            [CheckResult(self.exit_code(addresses), "", "")],
            checker_name=self.tool_name,
        )


class SuccessfulRequest(MockCheckRequest):
    tool_name = "Successful Checker"

    @classproperty
    def tool_id(cls) -> str:
        return "successfulchecker"

    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return 0


class FailingRequest(MockCheckRequest):
    tool_name = "Failing Checker"

    @classproperty
    def tool_id(cls) -> str:
        return "failingchecker"

    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return 1


class ConditionallySucceedsRequest(MockCheckRequest):
    tool_name = "Conditionally Succeeds Checker"

    @classproperty
    def tool_id(cls) -> str:
        return "conditionallysucceedschecker"

    @staticmethod
    def exit_code(addresses: Iterable[Address]) -> int:
        if any(address.target_name == "bad" for address in addresses):
            return 127
        return 0


class SkippedRequest(MockCheckRequest):
    tool_name = "Skipped Checker"

    @classproperty
    def tool_id(cls) -> str:
        return "skippedchecker"

    @staticmethod
    def exit_code(_) -> int:
        return 0

    @property
    def check_results(self) -> CheckResults:
        return CheckResults([], checker_name=self.tool_name)


class InvalidField(MultipleSourcesField):
    pass


class InvalidFieldSet(MockCheckFieldSet):
    required_fields = (InvalidField,)


class InvalidRequest(MockCheckRequest):
    field_set_type = InvalidFieldSet
    tool_name = "Invalid Checker"

    @classproperty
    def tool_id(cls) -> str:
        return "invalidchecker"

    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return -1


def make_target(address: Optional[Address] = None) -> Target:
    if address is None:
        address = Address("", target_name="tests")
    return MockTarget({}, address)


def run_typecheck_rule(
    *,
    request_types: Sequence[Type[CheckRequest]],
    targets: list[Target],
    only: list[str] | None = None,
) -> Tuple[int, str]:
    union_membership = UnionMembership({CheckRequest: request_types})
    check_subsystem = create_subsystem(CheckSubsystem, only=only or [])
    rule_runner = RuleRunner(bootstrap_args=["-lwarn"])
    with mock_console(rule_runner.options_bootstrapper) as (console, stdio_reader):
        result: Check = run_rule_with_mocks(
            check,
            rule_args=[
                console,
                Workspace(rule_runner.scheduler, _enforce_effects=False),
                Targets(targets),
                DistDir(relpath=Path("dist")),
                union_membership,
                check_subsystem,
            ],
            mock_gets=[
                MockGet(
                    output_type=CheckResults,
                    input_types=(
                        CheckRequest,
                        EnvironmentName,
                    ),
                    mock=lambda field_set_collection, _: field_set_collection.check_results,
                ),
                MockGet(
                    output_type=EnvironmentName,
                    input_types=(EnvironmentNameRequest,),
                    mock=lambda a: EnvironmentName(a.raw_value),
                ),
            ],
            union_membership=union_membership,
        )
        assert not stdio_reader.get_stdout()
        return result.exit_code, stdio_reader.get_stderr()


def test_invalid_target_noops() -> None:
    exit_code, stderr = run_typecheck_rule(request_types=[InvalidRequest], targets=[make_target()])
    assert exit_code == 0
    assert stderr == ""


def test_summary() -> None:
    good_address = Address("", target_name="good")
    bad_address = Address("", target_name="bad")
    targets = [make_target(good_address), make_target(bad_address)]
    requests = [
        ConditionallySucceedsRequest,
        FailingRequest,
        SkippedRequest,
        SuccessfulRequest,
    ]

    exit_code, stderr = run_typecheck_rule(request_types=requests, targets=targets)
    assert exit_code == FailingRequest.exit_code([bad_address])
    assert stderr == dedent(
        """\

        ✕ Conditionally Succeeds Checker failed.
        ✕ Failing Checker failed.
        ✓ Successful Checker succeeded.
        """
    )

    exit_code, stderr = run_typecheck_rule(
        request_types=requests,
        targets=targets,
        only=[FailingRequest.tool_id, SuccessfulRequest.tool_id],
    )
    assert stderr == dedent(
        """\

        ✕ Failing Checker failed.
        ✓ Successful Checker succeeded.
        """
    )


def test_streaming_output_skip() -> None:
    results = CheckResults([], checker_name="typechecker")
    assert results.level() == LogLevel.DEBUG
    assert results.message() == "typechecker skipped."


def test_streaming_output_success() -> None:
    results = CheckResults([CheckResult(0, "stdout", "stderr")], checker_name="typechecker")
    assert results.level() == LogLevel.INFO
    assert results.message() == dedent(
        """\
        typechecker succeeded.
        stdout
        stderr

        """
    )


def test_streaming_output_failure() -> None:
    results = CheckResults([CheckResult(18, "stdout", "stderr")], checker_name="typechecker")
    assert results.level() == LogLevel.ERROR
    assert results.message() == dedent(
        """\
        typechecker failed (exit code 18).
        stdout
        stderr

        """
    )


def test_streaming_output_partitions() -> None:
    results = CheckResults(
        [
            CheckResult(21, "", "", partition_description="ghc8.1"),
            CheckResult(0, "stdout", "stderr", partition_description="ghc9.2"),
        ],
        checker_name="typechecker",
    )
    assert results.level() == LogLevel.ERROR
    assert results.message() == dedent(
        """\
        typechecker failed (exit code 21).
        Partition #1 - ghc8.1:

        Partition #2 - ghc9.2:
        stdout
        stderr

        """
    )


def test_from_fallible_process_result_output_prepping() -> None:
    # Check that this calls the simplifier.
    class DistinctiveException(Exception):
        pass

    class SubSimplifier(Simplifier):
        def simplify(self, v: bytes | str) -> str:
            raise DistinctiveException()

    with pytest.raises(DistinctiveException):
        CheckResult.from_fallible_process_result(
            FallibleProcessResult(
                exit_code=0,
                stdout=b"",
                stdout_digest=EMPTY_FILE_DIGEST,
                stderr=b"",
                stderr_digest=EMPTY_FILE_DIGEST,
                output_digest=EMPTY_DIGEST,
                metadata=ProcessResultMetadata(
                    0,
                    ProcessExecutionEnvironment(
                        environment_name=None,
                        platform=Platform.create_for_localhost().value,
                        docker_image=None,
                        remote_execution=False,
                        remote_execution_extra_platform_properties=[],
                        execute_in_workspace=False,
                    ),
                    "ran_locally",
                    0,
                ),
            ),
            output_simplifier=SubSimplifier(),
        )
