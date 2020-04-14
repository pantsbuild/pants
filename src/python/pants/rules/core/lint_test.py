# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta, abstractmethod
from typing import Iterable, List, Tuple, Type

from pants.build_graph.address import Address
from pants.engine.legacy.graph import HydratedTargetsWithOrigins, HydratedTargetWithOrigin
from pants.engine.legacy.structs import TargetAdaptorWithOrigin
from pants.engine.rules import UnionMembership
from pants.rules.core.fmt_test import FmtTest
from pants.rules.core.lint import Lint, Linter, LintOptions, LintResult, lint
from pants.testutil.engine.util import MockConsole, MockGet, create_goal_subsystem, run_rule
from pants.testutil.test_base import TestBase
from pants.util.ordered_set import OrderedSet


class MockLinter(Linter, metaclass=ABCMeta):
    @staticmethod
    def is_valid_target(_: TargetAdaptorWithOrigin) -> bool:
        return True

    @staticmethod
    @abstractmethod
    def exit_code(_: Iterable[Address]) -> int:
        pass

    @staticmethod
    @abstractmethod
    def stdout(_: Iterable[Address]) -> str:
        pass

    @property
    def lint_result(self) -> LintResult:
        addresses = [
            adaptor_with_origin.adaptor.address
            for adaptor_with_origin in self.adaptors_with_origins
        ]
        return LintResult(self.exit_code(addresses), self.stdout(addresses), "")


class SuccessfulLinter(MockLinter):
    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return 0

    @staticmethod
    def stdout(addresses: Iterable[Address]) -> str:
        return f"Successful linter: {', '.join(str(address) for address in addresses)}"


class FailingLinter(MockLinter):
    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return 1

    @staticmethod
    def stdout(addresses: Iterable[Address]) -> str:
        return f"Failing linter: {', '.join(str(address) for address in addresses)}"


class ConditionallySucceedsLinter(MockLinter):
    @staticmethod
    def exit_code(addresses: Iterable[Address]) -> int:
        if any(address.target_name == "bad" for address in addresses):
            return 127
        return 0

    @staticmethod
    def stdout(addresses: Iterable[Address]) -> str:
        return f"Conditionally succeeds linter: {', '.join(str(address) for address in addresses)}"


class InvalidTargetLinter(MockLinter):
    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return -1

    @staticmethod
    def is_valid_target(_: TargetAdaptorWithOrigin) -> bool:
        return False

    @staticmethod
    def stdout(addresses: Iterable[Address]) -> str:
        return f"Invalid target linter: {', '.join(str(address) for address in addresses)}"


class LintTest(TestBase):
    @staticmethod
    def run_lint_rule(
        *,
        linters: List[Type[Linter]],
        targets: List[HydratedTargetWithOrigin],
        per_target_caching: bool,
    ) -> Tuple[int, str]:
        console = MockConsole(use_colors=False)
        union_membership = UnionMembership({Linter: OrderedSet(linters)})
        result: Lint = run_rule(
            lint,
            rule_args=[
                console,
                HydratedTargetsWithOrigins(targets),
                create_goal_subsystem(LintOptions, per_target_caching=per_target_caching),
                union_membership,
            ],
            mock_gets=[
                MockGet(
                    product_type=LintResult,
                    subject_type=Linter,
                    mock=lambda linter: linter.lint_result,
                ),
            ],
            union_membership=union_membership,
        )
        return result.exit_code, console.stdout.getvalue()

    def test_empty_target_noops(self) -> None:
        def assert_noops(per_target_caching: bool) -> None:
            exit_code, stdout = self.run_lint_rule(
                linters=[FailingLinter],
                targets=[FmtTest.make_hydrated_target_with_origin(include_sources=False)],
                per_target_caching=per_target_caching,
            )
            assert exit_code == 0
            assert stdout == ""

        assert_noops(per_target_caching=False)
        assert_noops(per_target_caching=True)

    def test_invalid_target_noops(self) -> None:
        def assert_noops(per_target_caching: bool) -> None:
            exit_code, stdout = self.run_lint_rule(
                linters=[InvalidTargetLinter],
                targets=[FmtTest.make_hydrated_target_with_origin()],
                per_target_caching=per_target_caching,
            )
            assert exit_code == 0
            assert stdout == ""

        assert_noops(per_target_caching=False)
        assert_noops(per_target_caching=True)

    def test_single_target_with_one_linter(self) -> None:
        def assert_expected(per_target_caching: bool) -> None:
            target_with_origin = FmtTest.make_hydrated_target_with_origin()
            address = target_with_origin.target.adaptor.address
            exit_code, stdout = self.run_lint_rule(
                linters=[FailingLinter],
                targets=[target_with_origin],
                per_target_caching=per_target_caching,
            )
            assert exit_code == FailingLinter.exit_code([address])
            assert stdout.strip() == FailingLinter.stdout([address])

        assert_expected(per_target_caching=False)
        assert_expected(per_target_caching=True)

    def test_single_target_with_multiple_linters(self) -> None:
        def assert_expected(per_target_caching: bool) -> None:
            target_with_origin = FmtTest.make_hydrated_target_with_origin()
            address = target_with_origin.target.adaptor.address
            exit_code, stdout = self.run_lint_rule(
                linters=[SuccessfulLinter, FailingLinter],
                targets=[target_with_origin],
                per_target_caching=per_target_caching,
            )
            assert exit_code == FailingLinter.exit_code([address])
            assert stdout.splitlines() == [
                SuccessfulLinter.stdout([address]),
                FailingLinter.stdout([address]),
            ]

        assert_expected(per_target_caching=False)
        assert_expected(per_target_caching=True)

    def test_multiple_targets_with_one_linter(self) -> None:
        good_target = FmtTest.make_hydrated_target_with_origin(name="good")
        bad_target = FmtTest.make_hydrated_target_with_origin(name="bad")
        addresses = [
            target_with_origin.target.adaptor.address
            for target_with_origin in (good_target, bad_target)
        ]

        def get_stdout(*, per_target_caching: bool) -> str:
            exit_code, stdout = self.run_lint_rule(
                linters=[ConditionallySucceedsLinter],
                targets=[good_target, bad_target],
                per_target_caching=per_target_caching,
            )
            assert exit_code == ConditionallySucceedsLinter.exit_code(
                [bad_target.target.adaptor.address]
            )
            return stdout

        stdout = get_stdout(per_target_caching=False)
        assert stdout.strip() == ConditionallySucceedsLinter.stdout(addresses)

        stdout = get_stdout(per_target_caching=True)
        assert stdout.splitlines() == [
            ConditionallySucceedsLinter.stdout([address]) for address in addresses
        ]

    def test_multiple_targets_with_multiple_linters(self) -> None:
        good_target = FmtTest.make_hydrated_target_with_origin(name="good")
        bad_target = FmtTest.make_hydrated_target_with_origin(name="bad")
        addresses = [
            target_with_origin.target.adaptor.address
            for target_with_origin in (good_target, bad_target)
        ]

        def get_stdout(*, per_target_caching: bool) -> str:
            exit_code, stdout = self.run_lint_rule(
                linters=[ConditionallySucceedsLinter, SuccessfulLinter],
                targets=[good_target, bad_target],
                per_target_caching=per_target_caching,
            )
            assert exit_code == ConditionallySucceedsLinter.exit_code(
                [bad_target.target.adaptor.address]
            )
            return stdout

        stdout = get_stdout(per_target_caching=False)
        assert stdout.splitlines() == [
            linter.stdout(addresses) for linter in [ConditionallySucceedsLinter, SuccessfulLinter]
        ]

        stdout = get_stdout(per_target_caching=True)
        assert stdout.splitlines() == [
            linter.stdout([address])
            for address in addresses
            for linter in [ConditionallySucceedsLinter, SuccessfulLinter]
        ]
