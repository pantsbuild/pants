# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta, abstractmethod
from typing import List, Tuple, Type

from pants.build_graph.address import Address
from pants.engine.legacy.graph import HydratedTargetsWithOrigins, HydratedTargetWithOrigin
from pants.engine.legacy.structs import TargetAdaptorWithOrigin
from pants.engine.rules import UnionMembership
from pants.rules.core.fmt_test import FmtTest
from pants.rules.core.lint import Lint, Linter, LintResult, lint
from pants.testutil.engine.util import MockConsole, MockGet, run_rule
from pants.testutil.test_base import TestBase


class MockLinter(Linter, metaclass=ABCMeta):
    @staticmethod
    def is_valid_target(_: TargetAdaptorWithOrigin) -> bool:
        return True

    @staticmethod
    @abstractmethod
    def exit_code(_: Address) -> int:
        pass

    @staticmethod
    @abstractmethod
    def stdout(_: Address) -> str:
        pass

    @property
    def target_address(self) -> Address:
        return self.adaptors_with_origins[0].adaptor.address

    @property
    def lint_result(self) -> LintResult:
        return LintResult(self.exit_code(self.target_address), self.stdout(self.target_address), "")


class SuccessfulLinter(MockLinter):
    @staticmethod
    def exit_code(_: Address) -> int:
        return 0

    @staticmethod
    def stdout(address: Address) -> str:
        return f"Successful linter: {address} was good."


class FailingLinter(MockLinter):
    @staticmethod
    def exit_code(_: Address) -> int:
        return 1

    @staticmethod
    def stdout(address: Address) -> str:
        return f"Failing linter: {address} was bad."


class ConditionallySucceedsLinter(MockLinter):
    @staticmethod
    def exit_code(address: Address) -> int:
        if address.target_name == "bad":
            return 127
        return 0

    @staticmethod
    def stdout(address: Address) -> str:
        if address.target_name == "bad":
            return f"Conditionally succeeds linter: {address} was bad."
        return f"Conditionally succeeds linter: {address} was good."


class InvalidTargetLinter(MockLinter):
    @staticmethod
    def exit_code(_: Address) -> int:
        return -1

    @staticmethod
    def is_valid_target(_: TargetAdaptorWithOrigin) -> bool:
        return False

    @staticmethod
    def stdout(address: Address) -> str:
        return f"Invalid target linter: {address} should not have run..."


class LintTest(TestBase):
    @staticmethod
    def run_lint_rule(
        *, linters: List[Type[Linter]], targets: List[HydratedTargetWithOrigin],
    ) -> Tuple[int, str]:
        console = MockConsole(use_colors=False)
        union_membership = UnionMembership({Linter: linters})
        result: Lint = run_rule(
            lint,
            rule_args=[console, HydratedTargetsWithOrigins(targets), union_membership],
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
        exit_code, stdout = self.run_lint_rule(
            linters=[FailingLinter],
            targets=[FmtTest.make_hydrated_target_with_origin(include_sources=False)],
        )
        assert exit_code == 0
        assert stdout == ""

    def test_invalid_target_noops(self) -> None:
        exit_code, stdout = self.run_lint_rule(
            linters=[InvalidTargetLinter], targets=[FmtTest.make_hydrated_target_with_origin()],
        )
        assert exit_code == 0
        assert stdout == ""

    def test_single_target_with_one_linter(self) -> None:
        target_with_origin = FmtTest.make_hydrated_target_with_origin()
        address = target_with_origin.target.adaptor.address
        exit_code, stdout = self.run_lint_rule(
            linters=[FailingLinter], targets=[target_with_origin]
        )
        assert exit_code == FailingLinter.exit_code(address)
        assert stdout.strip() == FailingLinter.stdout(address)

    def test_single_target_with_multiple_linters(self) -> None:
        target_with_origin = FmtTest.make_hydrated_target_with_origin()
        address = target_with_origin.target.adaptor.address
        exit_code, stdout = self.run_lint_rule(
            linters=[SuccessfulLinter, FailingLinter], targets=[target_with_origin],
        )
        assert exit_code == FailingLinter.exit_code(address)
        assert stdout.splitlines() == [
            SuccessfulLinter.stdout(address),
            FailingLinter.stdout(address),
        ]

    def test_multiple_targets_with_one_linter(self) -> None:
        good_target = FmtTest.make_hydrated_target_with_origin(name="good")
        bad_target = FmtTest.make_hydrated_target_with_origin(name="bad")
        exit_code, stdout = self.run_lint_rule(
            linters=[ConditionallySucceedsLinter], targets=[good_target, bad_target],
        )
        assert exit_code == ConditionallySucceedsLinter.exit_code(bad_target.target.adaptor.address)
        assert stdout.splitlines() == [
            ConditionallySucceedsLinter.stdout(target_with_origin.target.adaptor.address)
            for target_with_origin in [good_target, bad_target]
        ]

    def test_multiple_targets_with_multiple_linters(self) -> None:
        good_target = FmtTest.make_hydrated_target_with_origin(name="good")
        bad_target = FmtTest.make_hydrated_target_with_origin(name="bad")
        exit_code, stdout = self.run_lint_rule(
            linters=[ConditionallySucceedsLinter, SuccessfulLinter],
            targets=[good_target, bad_target],
        )
        assert exit_code == ConditionallySucceedsLinter.exit_code(bad_target.target.adaptor.address)
        assert stdout.splitlines() == [
            linter.stdout(target_with_origin.target.adaptor.address)
            for target_with_origin in [good_target, bad_target]
            for linter in [ConditionallySucceedsLinter, SuccessfulLinter]
        ]
