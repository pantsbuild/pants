# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from pathlib import Path
from textwrap import dedent
from typing import Iterable, Optional, Sequence, Tuple, Type

from pants.core.goals.check import (
    Check,
    CheckRequest,
    CheckResult,
    CheckResults,
    CheckSubsystem,
    check,
)
from pants.core.util_rules.distdir import DistDir
from pants.engine.addresses import Address
from pants.engine.fs import Workspace
from pants.engine.target import FieldSet, MultipleSourcesField, Target, Targets
from pants.engine.unions import UnionMembership
from pants.testutil.option_util import create_options_bootstrapper, create_subsystem
from pants.testutil.rule_runner import MockGet, RuleRunner, mock_console, run_rule_with_mocks
from pants.util.logging import LogLevel


class MockMultipleSourcesField(MultipleSourcesField):
    pass


class MockTarget(Target):
    alias = "mock_target"
    core_fields = (MockMultipleSourcesField,)


class MockCheckFieldSet(FieldSet):
    required_fields = (MockMultipleSourcesField,)


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
            checker_name=self.name,
        )


class SuccessfulRequest(MockCheckRequest):
    name = "SuccessfulChecker"

    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return 0


class FailingRequest(MockCheckRequest):
    name = "FailingChecker"

    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return 1


class ConditionallySucceedsRequest(MockCheckRequest):
    name = "ConditionallySucceedsChecker"

    @staticmethod
    def exit_code(addresses: Iterable[Address]) -> int:
        if any(address.target_name == "bad" for address in addresses):
            return 127
        return 0


class SkippedRequest(MockCheckRequest):
    name = "SkippedChecker"

    @staticmethod
    def exit_code(_) -> int:
        return 0

    @property
    def check_results(self) -> CheckResults:
        return CheckResults([], checker_name=self.name)


class InvalidField(MultipleSourcesField):
    pass


class InvalidFieldSet(MockCheckFieldSet):
    required_fields = (InvalidField,)


class InvalidRequest(MockCheckRequest):
    field_set_type = InvalidFieldSet
    name = "InvalidChecker"

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
    with mock_console(create_options_bootstrapper()) as (console, stdio_reader):
        rule_runner = RuleRunner()
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
                    input_type=CheckRequest,
                    mock=lambda field_set_collection: field_set_collection.check_results,
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

        ✕ ConditionallySucceedsChecker failed.
        ✕ FailingChecker failed.
        ✓ SuccessfulChecker succeeded.
        """
    )

    exit_code, stderr = run_typecheck_rule(
        request_types=requests, targets=targets, only=[FailingRequest.name, SuccessfulRequest.name]
    )
    assert stderr == dedent(
        """\

        ✕ FailingChecker failed.
        ✓ SuccessfulChecker succeeded.
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
