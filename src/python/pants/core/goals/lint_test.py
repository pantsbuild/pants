# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta, abstractmethod
from typing import Iterable, List, Optional, Tuple, Type

from pants.base.specs import SingleAddress
from pants.core.goals.lint import (
    Lint,
    LinterConfiguration,
    LinterConfigurations,
    LintOptions,
    LintResult,
    lint,
)
from pants.core.util_rules.filter_empty_sources import (
    ConfigurationsWithSources,
    ConfigurationsWithSourcesRequest,
)
from pants.engine.addresses import Address
from pants.engine.target import Sources, Target, TargetsWithOrigins, TargetWithOrigin
from pants.engine.unions import UnionMembership
from pants.testutil.engine.util import MockConsole, MockGet, create_goal_subsystem, run_rule
from pants.testutil.test_base import TestBase
from pants.util.ordered_set import OrderedSet


class MockTarget(Target):
    alias = "mock_target"
    core_fields = (Sources,)


class MockLinterConfiguration(LinterConfiguration):
    required_fields = (Sources,)


class MockLinterConfigurations(LinterConfigurations, metaclass=ABCMeta):
    config_type = MockLinterConfiguration

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
        return LintResult(self.exit_code(addresses), self.stdout(addresses), "")


class SuccessfulConfigurations(MockLinterConfigurations):
    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return 0

    @staticmethod
    def stdout(addresses: Iterable[Address]) -> str:
        return f"Successful linter: {', '.join(str(address) for address in addresses)}"


class FailingConfigurations(MockLinterConfigurations):
    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return 1

    @staticmethod
    def stdout(addresses: Iterable[Address]) -> str:
        return f"Failing linter: {', '.join(str(address) for address in addresses)}"


class ConditionallySucceedsConfigurations(MockLinterConfigurations):
    @staticmethod
    def exit_code(addresses: Iterable[Address]) -> int:
        if any(address.target_name == "bad" for address in addresses):
            return 127
        return 0

    @staticmethod
    def stdout(addresses: Iterable[Address]) -> str:
        return f"Conditionally succeeds linter: {', '.join(str(address) for address in addresses)}"


class InvalidField(Sources):
    pass


class InvalidConfiguration(MockLinterConfiguration):
    required_fields = (InvalidField,)


class InvalidConfigurations(MockLinterConfigurations):
    config_type = InvalidConfiguration

    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return -1

    @staticmethod
    def stdout(addresses: Iterable[Address]) -> str:
        return f"Invalid target linter: {', '.join(str(address) for address in addresses)}"


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
        config_collection_types: List[Type[LinterConfigurations]],
        targets: List[TargetWithOrigin],
        per_target_caching: bool,
        include_sources: bool = True,
    ) -> Tuple[int, str]:
        console = MockConsole(use_colors=False)
        union_membership = UnionMembership(
            {LinterConfigurations: OrderedSet(config_collection_types)}
        )
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
                    subject_type=LinterConfigurations,
                    mock=lambda config_collection: config_collection.lint_result,
                ),
                MockGet(
                    product_type=ConfigurationsWithSources,
                    subject_type=ConfigurationsWithSourcesRequest,
                    mock=lambda configs: ConfigurationsWithSources(
                        configs if include_sources else ()
                    ),
                ),
            ],
            union_membership=union_membership,
        )
        return result.exit_code, console.stdout.getvalue()

    def test_empty_target_noops(self) -> None:
        def assert_noops(per_target_caching: bool) -> None:
            exit_code, stdout = self.run_lint_rule(
                config_collection_types=[FailingConfigurations],
                targets=[self.make_target_with_origin()],
                per_target_caching=per_target_caching,
                include_sources=False,
            )
            assert exit_code == 0
            assert stdout == ""

        assert_noops(per_target_caching=False)
        assert_noops(per_target_caching=True)

    def test_invalid_target_noops(self) -> None:
        def assert_noops(per_target_caching: bool) -> None:
            exit_code, stdout = self.run_lint_rule(
                config_collection_types=[InvalidConfigurations],
                targets=[self.make_target_with_origin()],
                per_target_caching=per_target_caching,
            )
            assert exit_code == 0
            assert stdout == ""

        assert_noops(per_target_caching=False)
        assert_noops(per_target_caching=True)

    def test_single_target_with_one_linter(self) -> None:
        address = Address.parse(":tests")
        target_with_origin = self.make_target_with_origin(address)

        def assert_expected(per_target_caching: bool) -> None:
            exit_code, stdout = self.run_lint_rule(
                config_collection_types=[FailingConfigurations],
                targets=[target_with_origin],
                per_target_caching=per_target_caching,
            )
            assert exit_code == FailingConfigurations.exit_code([address])
            assert stdout.strip() == FailingConfigurations.stdout([address])

        assert_expected(per_target_caching=False)
        assert_expected(per_target_caching=True)

    def test_single_target_with_multiple_linters(self) -> None:
        address = Address.parse(":tests")
        target_with_origin = self.make_target_with_origin(address)

        def assert_expected(per_target_caching: bool) -> None:
            exit_code, stdout = self.run_lint_rule(
                config_collection_types=[SuccessfulConfigurations, FailingConfigurations],
                targets=[target_with_origin],
                per_target_caching=per_target_caching,
            )
            assert exit_code == FailingConfigurations.exit_code([address])
            assert stdout.splitlines() == [
                SuccessfulConfigurations.stdout([address]),
                FailingConfigurations.stdout([address]),
            ]

        assert_expected(per_target_caching=False)
        assert_expected(per_target_caching=True)

    def test_multiple_targets_with_one_linter(self) -> None:
        good_address = Address.parse(":good")
        bad_address = Address.parse(":bad")

        def get_stdout(*, per_target_caching: bool) -> str:
            exit_code, stdout = self.run_lint_rule(
                config_collection_types=[ConditionallySucceedsConfigurations],
                targets=[
                    self.make_target_with_origin(good_address),
                    self.make_target_with_origin(bad_address),
                ],
                per_target_caching=per_target_caching,
            )
            assert exit_code == ConditionallySucceedsConfigurations.exit_code([bad_address])
            return stdout

        stdout = get_stdout(per_target_caching=False)
        assert stdout.strip() == ConditionallySucceedsConfigurations.stdout(
            [good_address, bad_address]
        )

        stdout = get_stdout(per_target_caching=True)
        assert stdout.splitlines() == [
            ConditionallySucceedsConfigurations.stdout([address])
            for address in [good_address, bad_address]
        ]

    def test_multiple_targets_with_multiple_linters(self) -> None:
        good_address = Address.parse(":good")
        bad_address = Address.parse(":bad")

        def get_stdout(*, per_target_caching: bool) -> str:
            exit_code, stdout = self.run_lint_rule(
                config_collection_types=[
                    ConditionallySucceedsConfigurations,
                    SuccessfulConfigurations,
                ],
                targets=[
                    self.make_target_with_origin(good_address),
                    self.make_target_with_origin(bad_address),
                ],
                per_target_caching=per_target_caching,
            )
            assert exit_code == ConditionallySucceedsConfigurations.exit_code([bad_address])
            return stdout

        stdout = get_stdout(per_target_caching=False)
        assert stdout.splitlines() == [
            config_collection.stdout([good_address, bad_address])
            for config_collection in [ConditionallySucceedsConfigurations, SuccessfulConfigurations]
        ]

        stdout = get_stdout(per_target_caching=True)
        assert stdout.splitlines() == [
            config_collection.stdout([address])
            for config_collection in [ConditionallySucceedsConfigurations, SuccessfulConfigurations]
            for address in [good_address, bad_address]
        ]
