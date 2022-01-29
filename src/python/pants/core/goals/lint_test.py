# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta, abstractmethod
from pathlib import Path
from textwrap import dedent
from typing import Iterable, List, Optional, Tuple, Type

import pytest

from pants.core.goals.lint import (
    Lint,
    LintFilesRequest,
    LintRequest,
    LintResult,
    LintResults,
    LintSubsystem,
    lint,
)
from pants.core.util_rules.distdir import DistDir
from pants.engine.addresses import Address
from pants.engine.fs import SpecsSnapshot, Workspace
from pants.engine.target import FieldSet, MultipleSourcesField, Target, Targets
from pants.engine.unions import UnionMembership
from pants.testutil.option_util import create_goal_subsystem
from pants.testutil.rule_runner import MockGet, RuleRunner, mock_console, run_rule_with_mocks
from pants.util.logging import LogLevel


class MockTarget(Target):
    alias = "mock_target"
    core_fields = (MultipleSourcesField,)


class MockLinterFieldSet(FieldSet):
    required_fields = (MultipleSourcesField,)


class MockLintRequest(LintRequest, metaclass=ABCMeta):
    field_set_type = MockLinterFieldSet

    @staticmethod
    @abstractmethod
    def exit_code(_: Iterable[Address]) -> int:
        pass

    @property
    def lint_results(self) -> LintResults:
        addresses = [config.address for config in self.field_sets]
        return LintResults([LintResult(self.exit_code(addresses), "", "")], linter_name=self.name)


class SuccessfulRequest(MockLintRequest):
    name = "SuccessfulLinter"

    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return 0


class FailingRequest(MockLintRequest):
    name = "FailingLinter"

    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return 1


class ConditionallySucceedsRequest(MockLintRequest):
    name = "ConditionallySucceedsLinter"

    @staticmethod
    def exit_code(addresses: Iterable[Address]) -> int:
        if any(address.target_name == "bad" for address in addresses):
            return 127
        return 0


class SkippedRequest(MockLintRequest):
    name = "SkippedLinter"

    @staticmethod
    def exit_code(_) -> int:
        return 0

    @property
    def lint_results(self) -> LintResults:
        return LintResults([], linter_name=self.name)


class InvalidField(MultipleSourcesField):
    pass


class InvalidFieldSet(MockLinterFieldSet):
    required_fields = (InvalidField,)


class InvalidRequest(MockLintRequest):
    field_set_type = InvalidFieldSet
    name = "InvalidLinter"

    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return -1


class MockFilesRequest(LintFilesRequest):
    name = "FilesLinter"

    @property
    def lint_results(self) -> LintResults:
        return LintResults([LintResult(0, "", "")], linter_name=self.name)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner()


def make_target(address: Optional[Address] = None) -> Target:
    return MockTarget({}, address or Address("", target_name="tests"))


def run_lint_rule(
    rule_runner: RuleRunner,
    *,
    lint_request_types: List[Type[LintRequest]],
    targets: List[Target],
    run_files_linter: bool = False,
    per_file_caching: bool = False,
    batch_size: int = 128,
) -> Tuple[int, str]:
    union_membership = UnionMembership(
        {
            LintRequest: lint_request_types,
            LintFilesRequest: [MockFilesRequest] if run_files_linter else [],
        }
    )
    lint_subsystem = create_goal_subsystem(
        LintSubsystem,
        per_file_caching=per_file_caching,
        batch_size=batch_size,
    )
    specs_snapshot = SpecsSnapshot(rule_runner.make_snapshot_of_empty_files(["f.txt"]))
    with mock_console(rule_runner.options_bootstrapper) as (console, stdio_reader):
        result: Lint = run_rule_with_mocks(
            lint,
            rule_args=[
                console,
                Workspace(rule_runner.scheduler, _enforce_effects=False),
                Targets(targets),
                specs_snapshot,
                lint_subsystem,
                union_membership,
                DistDir(relpath=Path("dist")),
            ],
            mock_gets=[
                MockGet(
                    output_type=LintResults,
                    input_type=LintRequest,
                    mock=lambda mock_request: mock_request.lint_results,
                ),
                MockGet(
                    output_type=LintResults,
                    input_type=LintFilesRequest,
                    mock=lambda mock_request: mock_request.lint_results,
                ),
            ],
            union_membership=union_membership,
        )
        assert not stdio_reader.get_stdout()
        return result.exit_code, stdio_reader.get_stderr()


@pytest.mark.parametrize("per_file_caching", [True, False])
def test_invalid_target_noops(rule_runner: RuleRunner, per_file_caching: bool) -> None:
    exit_code, stderr = run_lint_rule(
        rule_runner,
        lint_request_types=[InvalidRequest],
        targets=[make_target()],
        per_file_caching=per_file_caching,
    )
    assert exit_code == 0
    assert stderr == ""


@pytest.mark.parametrize("per_file_caching", [True, False])
def test_summary(rule_runner: RuleRunner, per_file_caching: bool) -> None:
    """Test that we render the summary correctly.

    This tests that we:
    * Merge multiple results belonging to the same linter (`--per-file-caching`).
    * Decide correctly between skipped, failed, and succeeded.
    """
    good_address = Address("", target_name="good")
    bad_address = Address("", target_name="bad")

    exit_code, stderr = run_lint_rule(
        rule_runner,
        lint_request_types=[
            ConditionallySucceedsRequest,
            FailingRequest,
            SkippedRequest,
            SuccessfulRequest,
        ],
        targets=[make_target(good_address), make_target(bad_address)],
        per_file_caching=per_file_caching,
        run_files_linter=True,
    )
    assert exit_code == FailingRequest.exit_code([bad_address])
    assert stderr == dedent(
        """\

        𐄂 ConditionallySucceedsLinter failed.
        𐄂 FailingLinter failed.
        ✓ FilesLinter succeeded.
        ✓ SuccessfulLinter succeeded.
        """
    )


@pytest.mark.parametrize("batch_size", [1, 32, 128, 1024])
def test_batched(rule_runner: RuleRunner, batch_size: int) -> None:
    exit_code, stderr = run_lint_rule(
        rule_runner,
        lint_request_types=[
            ConditionallySucceedsRequest,
            FailingRequest,
            SkippedRequest,
            SuccessfulRequest,
        ],
        targets=[make_target(Address("", target_name=f"good{i}")) for i in range(0, 512)],
        batch_size=batch_size,
    )
    assert exit_code == FailingRequest.exit_code([])
    assert stderr == dedent(
        """\

        ✓ ConditionallySucceedsLinter succeeded.
        𐄂 FailingLinter failed.
        ✓ SuccessfulLinter succeeded.
        """
    )


def test_streaming_output_skip() -> None:
    results = LintResults([], linter_name="linter")
    assert results.level() == LogLevel.DEBUG
    assert results.message() == "linter skipped."


def test_streaming_output_success() -> None:
    results = LintResults([LintResult(0, "stdout", "stderr")], linter_name="linter")
    assert results.level() == LogLevel.INFO
    assert results.message() == dedent(
        """\
        linter succeeded.
        stdout
        stderr

        """
    )


def test_streaming_output_failure() -> None:
    results = LintResults([LintResult(18, "stdout", "stderr")], linter_name="linter")
    assert results.level() == LogLevel.ERROR
    assert results.message() == dedent(
        """\
        linter failed (exit code 18).
        stdout
        stderr

        """
    )


def test_streaming_output_partitions() -> None:
    results = LintResults(
        [
            LintResult(21, "", "", partition_description="ghc8.1"),
            LintResult(0, "stdout", "stderr", partition_description="ghc9.2"),
        ],
        linter_name="linter",
    )
    assert results.level() == LogLevel.ERROR
    assert results.message() == dedent(
        """\
        linter failed (exit code 21).
        Partition #1 - ghc8.1:

        Partition #2 - ghc9.2:
        stdout
        stderr

        """
    )
