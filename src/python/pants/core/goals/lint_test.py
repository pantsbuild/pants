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
from pants.testutil.engine.util import MockConsole, MockGet, create_goal_subsystem, run_rule
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
        per_target_caching: bool,
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
                create_goal_subsystem(LintSubsystem, per_target_caching=per_target_caching),
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
        def assert_noops(per_target_caching: bool) -> None:
            exit_code, stderr = self.run_lint_rule(
                lint_request_types=[FailingRequest],
                targets=[self.make_target()],
                per_target_caching=per_target_caching,
                include_sources=False,
            )
            assert exit_code == 0
            assert stderr == ""

        assert_noops(per_target_caching=False)
        assert_noops(per_target_caching=True)

    def test_invalid_target_noops(self) -> None:
        def assert_noops(per_target_caching: bool) -> None:
            exit_code, stderr = self.run_lint_rule(
                lint_request_types=[InvalidRequest],
                targets=[self.make_target()],
                per_target_caching=per_target_caching,
            )
            assert exit_code == 0
            assert stderr == ""

        assert_noops(per_target_caching=False)
        assert_noops(per_target_caching=True)

    def test_single_target_with_one_linter(self) -> None:
        address = Address.parse(":tests")
        target = self.make_target(address)

        def assert_expected(per_target_caching: bool) -> None:
            exit_code, stderr = self.run_lint_rule(
                lint_request_types=[FailingRequest],
                targets=[target],
                per_target_caching=per_target_caching,
            )
            assert exit_code == FailingRequest.exit_code([address])
            assert stderr == "𐄂 FailingLinter failed.\n"

        assert_expected(per_target_caching=False)
        assert_expected(per_target_caching=True)

    def test_single_target_with_multiple_linters(self) -> None:
        address = Address.parse(":tests")
        target = self.make_target(address)

        def assert_expected(per_target_caching: bool) -> None:
            exit_code, stderr = self.run_lint_rule(
                lint_request_types=[SuccessfulRequest, FailingRequest],
                targets=[target],
                per_target_caching=per_target_caching,
            )
            assert exit_code == FailingRequest.exit_code([address])
            assert stderr == dedent(
                """\
                𐄂 FailingLinter failed.
                ✓ SuccessfulLinter succeeded.
                """
            )

        assert_expected(per_target_caching=False)
        assert_expected(per_target_caching=True)

    def test_merge_per_target_caching(self) -> None:
        """Even if the user used `--per-target-caching`, the final summary should only show one
        result for each linter.

        The linter should report any failing error code, even if some of its results succeeded.
        """
        good_address = Address.parse(":good")
        bad_address = Address.parse(":bad")

        def assert_expected(*, per_target_caching: bool) -> None:
            exit_code, stderr = self.run_lint_rule(
                lint_request_types=[ConditionallySucceedsRequest, SuccessfulRequest],
                targets=[self.make_target(good_address), self.make_target(bad_address),],
                per_target_caching=per_target_caching,
            )
            assert exit_code == ConditionallySucceedsRequest.exit_code([bad_address])
            assert stderr == dedent(
                """\
                𐄂 ConditionallySucceedsLinter failed.
                ✓ SuccessfulLinter succeeded.
                """
            )

        assert_expected(per_target_caching=False)
        assert_expected(per_target_caching=True)


def test_streaming_output_skip() -> None:
    results = LintResults([], linter_name="linter")
    assert results.level() == LogLevel.DEBUG
    assert results.message() == "skipped."


def test_streaming_output_success() -> None:
    results = LintResults([LintResult(0, "stdout", "stderr", report=None)], linter_name="linter")
    assert results.level() == LogLevel.INFO
    assert results.message() == dedent(
        """\
        succeeded.
        stdout
        stderr

        """
    )


def test_streaming_output_failure() -> None:
    results = LintResults([LintResult(1, "stdout", "stderr", report=None)], linter_name="linter")
    assert results.level() == LogLevel.WARN
    assert results.message() == dedent(
        """\
        failed.
        stdout
        stderr

        """
    )


def test_streaming_output_partitions() -> None:
    results = LintResults(
        [
            LintResult(1, "stdout", "stderr", report=None),
            LintResult(0, "stdout", "stderr", report=None),
        ],
        linter_name="linter",
    )
    assert results.level() == LogLevel.WARN
    assert results.message() == dedent(
        """\
        failed.
        Partition #1:
        stdout
        stderr

        Partition #2:
        stdout
        stderr

        """
    )
