# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta, abstractmethod
from textwrap import dedent
from typing import ClassVar, Iterable, List, Optional, Tuple, Type

from pants.base.specs import SingleAddress
from pants.core.goals.lint import (
    Lint,
    LinterFieldSet,
    LinterFieldSets,
    LintOptions,
    LintResult,
    lint,
)
from pants.core.util_rules.filter_empty_sources import (
    FieldSetsWithSources,
    FieldSetsWithSourcesRequest,
)
from pants.engine.addresses import Address
from pants.engine.target import Sources, Target, TargetsWithOrigins, TargetWithOrigin
from pants.engine.unions import UnionMembership
from pants.testutil.engine.util import MockConsole, MockGet, create_goal_subsystem, run_rule
from pants.testutil.test_base import TestBase


class MockTarget(Target):
    alias = "mock_target"
    core_fields = (Sources,)


class MockLinterFieldSet(LinterFieldSet):
    required_fields = (Sources,)


class MockLinterFieldSets(LinterFieldSets, metaclass=ABCMeta):
    field_set_type = MockLinterFieldSet
    linter_name: ClassVar[str]

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
        addresses = [config.address for config in self]
        return LintResult(
            self.exit_code(addresses), self.stdout(addresses), "", linter_name=self.linter_name
        )


class SuccessfulFieldSets(MockLinterFieldSets):
    linter_name = "SuccessfulLinter"

    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return 0

    @staticmethod
    def stdout(addresses: Iterable[Address]) -> str:
        return ", ".join(str(address) for address in addresses)


class FailingFieldSets(MockLinterFieldSets):
    linter_name = "FailingLinter"

    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return 1

    @staticmethod
    def stdout(addresses: Iterable[Address]) -> str:
        return ", ".join(str(address) for address in addresses)


class ConditionallySucceedsFieldSets(MockLinterFieldSets):
    linter_name = "ConditionallySucceedsLinter"

    @staticmethod
    def exit_code(addresses: Iterable[Address]) -> int:
        if any(address.target_name == "bad" for address in addresses):
            return 127
        return 0

    @staticmethod
    def stdout(addresses: Iterable[Address]) -> str:
        return ", ".join(str(address) for address in addresses)


class InvalidField(Sources):
    pass


class InvalidFieldSet(MockLinterFieldSet):
    required_fields = (InvalidField,)


class InvalidFieldSets(MockLinterFieldSets):
    field_set_type = InvalidFieldSet
    linter_name = "InvalidLinter"

    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return -1

    @staticmethod
    def stdout(addresses: Iterable[Address]) -> str:
        return ", ".join(str(address) for address in addresses)


class LintTest(TestBase):
    @staticmethod
    def make_target_with_origin(address: Optional[Address] = None) -> TargetWithOrigin:
        if address is None:
            address = Address.parse(":tests")
        return TargetWithOrigin(
            MockTarget({}, address=address),
            origin=SingleAddress(directory=address.spec_path, name=address.target_name),
        )

    @staticmethod
    def run_lint_rule(
        *,
        field_set_collection_types: List[Type[LinterFieldSets]],
        targets: List[TargetWithOrigin],
        per_target_caching: bool,
        include_sources: bool = True,
    ) -> Tuple[int, str]:
        console = MockConsole(use_colors=False)
        union_membership = UnionMembership({LinterFieldSets: field_set_collection_types})
        result: Lint = run_rule(
            lint,
            rule_args=[
                console,
                TargetsWithOrigins(targets),
                create_goal_subsystem(LintOptions, per_target_caching=per_target_caching),
                union_membership,
            ],
            mock_gets=[
                MockGet(
                    product_type=LintResult,
                    subject_type=LinterFieldSets,
                    mock=lambda field_set_collection: field_set_collection.lint_result,
                ),
                MockGet(
                    product_type=FieldSetsWithSources,
                    subject_type=FieldSetsWithSourcesRequest,
                    mock=lambda field_sets: FieldSetsWithSources(
                        field_sets if include_sources else ()
                    ),
                ),
            ],
            union_membership=union_membership,
        )
        assert not console.stdout.getvalue()
        return result.exit_code, console.stderr.getvalue()

    def test_empty_target_noops(self) -> None:
        def assert_noops(per_target_caching: bool) -> None:
            exit_code, stderr = self.run_lint_rule(
                field_set_collection_types=[FailingFieldSets],
                targets=[self.make_target_with_origin()],
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
                field_set_collection_types=[InvalidFieldSets],
                targets=[self.make_target_with_origin()],
                per_target_caching=per_target_caching,
            )
            assert exit_code == 0
            assert stderr == ""

        assert_noops(per_target_caching=False)
        assert_noops(per_target_caching=True)

    def test_single_target_with_one_linter(self) -> None:
        address = Address.parse(":tests")
        target_with_origin = self.make_target_with_origin(address)

        def assert_expected(per_target_caching: bool) -> None:
            exit_code, stderr = self.run_lint_rule(
                field_set_collection_types=[FailingFieldSets],
                targets=[target_with_origin],
                per_target_caching=per_target_caching,
            )
            assert exit_code == FailingFieldSets.exit_code([address])
            assert stderr == dedent(
                f"""\
                𐄂 FailingLinter failed.
                {FailingFieldSets.stdout([address])}
                """
            )

        assert_expected(per_target_caching=False)
        assert_expected(per_target_caching=True)

    def test_single_target_with_multiple_linters(self) -> None:
        address = Address.parse(":tests")
        target_with_origin = self.make_target_with_origin(address)

        def assert_expected(per_target_caching: bool) -> None:
            exit_code, stderr = self.run_lint_rule(
                field_set_collection_types=[SuccessfulFieldSets, FailingFieldSets],
                targets=[target_with_origin],
                per_target_caching=per_target_caching,
            )
            assert exit_code == FailingFieldSets.exit_code([address])
            assert stderr == dedent(
                f"""\
                𐄂 FailingLinter failed.
                {FailingFieldSets.stdout([address])}

                ✓ SuccessfulLinter succeeded.
                {SuccessfulFieldSets.stdout([address])}
                """
            )

        assert_expected(per_target_caching=False)
        assert_expected(per_target_caching=True)

    def test_multiple_targets_with_one_linter(self) -> None:
        good_address = Address.parse(":good")
        bad_address = Address.parse(":bad")

        def get_stderr(*, per_target_caching: bool) -> str:
            exit_code, stderr = self.run_lint_rule(
                field_set_collection_types=[ConditionallySucceedsFieldSets],
                targets=[
                    self.make_target_with_origin(good_address),
                    self.make_target_with_origin(bad_address),
                ],
                per_target_caching=per_target_caching,
            )
            assert exit_code == ConditionallySucceedsFieldSets.exit_code([bad_address])
            return stderr

        assert get_stderr(per_target_caching=False) == dedent(
            f"""\
            𐄂 ConditionallySucceedsLinter failed.
            {ConditionallySucceedsFieldSets.stdout([good_address, bad_address])}
            """
        )

        assert get_stderr(per_target_caching=True) == dedent(
            f"""\
            ✓ ConditionallySucceedsLinter succeeded.
            {ConditionallySucceedsFieldSets.stdout([good_address])}

            𐄂 ConditionallySucceedsLinter failed.
            {ConditionallySucceedsFieldSets.stdout([bad_address])}
            """
        )

    def test_multiple_targets_with_multiple_linters(self) -> None:
        good_address = Address.parse(":good")
        bad_address = Address.parse(":bad")

        def get_stderr(*, per_target_caching: bool) -> str:
            exit_code, stderr = self.run_lint_rule(
                field_set_collection_types=[ConditionallySucceedsFieldSets, SuccessfulFieldSets,],
                targets=[
                    self.make_target_with_origin(good_address),
                    self.make_target_with_origin(bad_address),
                ],
                per_target_caching=per_target_caching,
            )
            assert exit_code == ConditionallySucceedsFieldSets.exit_code([bad_address])
            return stderr

        assert get_stderr(per_target_caching=False) == dedent(
            f"""\
            𐄂 ConditionallySucceedsLinter failed.
            {ConditionallySucceedsFieldSets.stdout([good_address, bad_address])}

            ✓ SuccessfulLinter succeeded.
            {SuccessfulFieldSets.stdout([good_address, bad_address])}
            """
        )

        assert get_stderr(per_target_caching=True) == dedent(
            f"""\
            ✓ ConditionallySucceedsLinter succeeded.
            {ConditionallySucceedsFieldSets.stdout([good_address])}

            𐄂 ConditionallySucceedsLinter failed.
            {ConditionallySucceedsFieldSets.stdout([bad_address])}

            ✓ SuccessfulLinter succeeded.
            {SuccessfulFieldSets.stdout([good_address])}

            ✓ SuccessfulLinter succeeded.
            {SuccessfulFieldSets.stdout([bad_address])}
            """
        )
