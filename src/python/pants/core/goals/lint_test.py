# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta, abstractmethod
from textwrap import dedent
from typing import ClassVar, Iterable, List, Optional, Tuple, Type

from pants.core.goals.lint import Lint, LintRequest, LintResult, LintResults, LintSubsystem, lint
from pants.core.util_rules.filter_empty_sources import (
    FieldSetsWithSources,
    FieldSetsWithSourcesRequest,
)
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST, Digest, MergeDigests, Workspace
from pants.engine.target import FieldSet, Sources, Target, Targets
from pants.engine.unions import UnionMembership
from pants.testutil.engine_util import MockConsole, MockGet, run_rule
from pants.testutil.option_util import create_goal_subsystem
from pants.testutil.test_base import TestBase
from pants.util.logging import LogLevel


class MockTarget(Target):
    alias = "mock_target"
    core_fields = (Sources,)


class MockLinterFieldSet(FieldSet):
    required_fields = (Sources,)


class MockLintRequest(LintRequest, metaclass=ABCMeta):
    field_set_type = MockLinterFieldSet
    linter_name: ClassVar[str]

    @staticmethod
    @abstractmethod
    def exit_code(_: Iterable[Address]) -> int:
        pass

    @property
    def lint_results(self) -> LintResults:
        addresses = [config.address for config in self.field_sets]
        return LintResults(
            [LintResult(self.exit_code(addresses), "", "", report=None)],
            linter_name=self.linter_name,
        )


class SuccessfulRequest(MockLintRequest):
    linter_name = "SuccessfulLinter"

    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return 0


class FailingRequest(MockLintRequest):
    linter_name = "FailingLinter"

    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return 1


class ConditionallySucceedsRequest(MockLintRequest):
    linter_name = "ConditionallySucceedsLinter"

    @staticmethod
    def exit_code(addresses: Iterable[Address]) -> int:
        if any(address.target_name == "bad" for address in addresses):
            return 127
        return 0


class SkippedRequest(MockLintRequest):
    @staticmethod
    def exit_code(_) -> int:
        return 0

    @property
    def lint_results(self) -> LintResults:
        return LintResults([], linter_name="SkippedLinter")


class InvalidField(Sources):
    pass


class InvalidFieldSet(MockLinterFieldSet):
    required_fields = (InvalidField,)


class InvalidRequest(MockLintRequest):
    field_set_type = InvalidFieldSet
    linter_name = "InvalidLinter"

    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return -1


class LintTest(TestBase):
    @staticmethod
    def make_target(address: Optional[Address] = None) -> Target:
        return MockTarget({}, address=address or Address.parse(":tests"))

    def run_lint_rule(
        self,
        *,
        lint_request_types: List[Type[LintRequest]],
        targets: List[Target],
        per_file_caching: bool,
        include_sources: bool = True,
    ) -> Tuple[int, str]:
        console = MockConsole(use_colors=False)
        workspace = Workspace(self.scheduler)
        union_membership = UnionMembership({LintRequest: lint_request_types})
        result: Lint = run_rule(
            lint,
            rule_args=[
                console,
                workspace,
                Targets(targets),
                create_goal_subsystem(
                    LintSubsystem, per_file_caching=per_file_caching, per_target_caching=False
                ),
                union_membership,
            ],
            mock_gets=[
                MockGet(
                    product_type=LintResults,
                    subject_type=LintRequest,
                    mock=lambda field_set_collection: field_set_collection.lint_results,
                ),
                MockGet(
                    product_type=FieldSetsWithSources,
                    subject_type=FieldSetsWithSourcesRequest,
                    mock=lambda field_sets: FieldSetsWithSources(
                        field_sets if include_sources else ()
                    ),
                ),
                MockGet(
                    product_type=Digest, subject_type=MergeDigests, mock=lambda _: EMPTY_DIGEST
                ),
            ],
            union_membership=union_membership,
        )
        assert not console.stdout.getvalue()
        return result.exit_code, console.stderr.getvalue()

    def test_empty_target_noops(self) -> None:
        def assert_noops(per_file_caching: bool) -> None:
            exit_code, stderr = self.run_lint_rule(
                lint_request_types=[FailingRequest],
                targets=[self.make_target()],
                per_file_caching=per_file_caching,
                include_sources=False,
            )
            assert exit_code == 0
            assert stderr == ""

        assert_noops(per_file_caching=False)
        assert_noops(per_file_caching=True)

    def test_invalid_target_noops(self) -> None:
        def assert_noops(per_file_caching: bool) -> None:
            exit_code, stderr = self.run_lint_rule(
                lint_request_types=[InvalidRequest],
                targets=[self.make_target()],
                per_file_caching=per_file_caching,
            )
            assert exit_code == 0
            assert stderr == ""

        assert_noops(per_file_caching=False)
        assert_noops(per_file_caching=True)

    def test_summary(self) -> None:
        """Test that we render the summary correctly.

        This tests that we:
        * Merge multiple results belonging to the same linter (`--per-file-caching`).
        * Decide correctly between skipped, failed, and succeeded.
        """
        good_address = Address.parse(":good")
        bad_address = Address.parse(":bad")

        def assert_expected(*, per_file_caching: bool) -> None:
            exit_code, stderr = self.run_lint_rule(
                lint_request_types=[
                    ConditionallySucceedsRequest,
                    FailingRequest,
                    SkippedRequest,
                    SuccessfulRequest,
                ],
                targets=[self.make_target(good_address), self.make_target(bad_address)],
                per_file_caching=per_file_caching,
            )
            assert exit_code == FailingRequest.exit_code([bad_address])
            assert stderr == dedent(
                """\

                𐄂 ConditionallySucceedsLinter failed.
                𐄂 FailingLinter failed.
                - SkippedLinter skipped.
                ✓ SuccessfulLinter succeeded.
                """
            )

        assert_expected(per_file_caching=False)
        assert_expected(per_file_caching=True)


def test_streaming_output_skip() -> None:
    results = LintResults([], linter_name="linter")
    assert results.level() == LogLevel.DEBUG
    assert results.message() == "skipped."


def test_streaming_output_success() -> None:
    results = LintResults([LintResult(0, "stdout", "stderr")], linter_name="linter")
    assert results.level() == LogLevel.INFO
    assert results.message() == dedent(
        """\
        succeeded.
        stdout
        stderr

        """
    )


def test_streaming_output_failure() -> None:
    results = LintResults([LintResult(18, "stdout", "stderr")], linter_name="linter")
    assert results.level() == LogLevel.WARN
    assert results.message() == dedent(
        """\
        failed (exit code 18).
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
    assert results.level() == LogLevel.WARN
    assert results.message() == dedent(
        """\
        failed (exit code 21).
        Partition #1 - ghc8.1:

        Partition #2 - ghc9.2:
        stdout
        stderr

        """
    )
