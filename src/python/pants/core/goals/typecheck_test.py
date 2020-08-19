# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta, abstractmethod
from textwrap import dedent
from typing import ClassVar, Iterable, List, Optional, Tuple, Type

from pants.base.specs import AddressLiteralSpec
from pants.core.goals.typecheck import (
    Typecheck,
    TypecheckRequest,
    TypecheckResult,
    TypecheckResults,
    typecheck,
)
from pants.core.util_rules.filter_empty_sources import (
    FieldSetsWithSources,
    FieldSetsWithSourcesRequest,
)
from pants.engine.addresses import Address
from pants.engine.target import (
    FieldSetWithOrigin,
    Sources,
    Target,
    TargetsWithOrigins,
    TargetWithOrigin,
)
from pants.engine.unions import UnionMembership
from pants.testutil.engine.util import MockConsole, MockGet, run_rule
from pants.testutil.test_base import TestBase
from pants.util.logging import LogLevel


class MockTarget(Target):
    alias = "mock_target"
    core_fields = (Sources,)


class MockTypecheckFieldSet(FieldSetWithOrigin):
    required_fields = (Sources,)


class MockTypecheckRequest(TypecheckRequest, metaclass=ABCMeta):
    field_set_type = MockTypecheckFieldSet
    typechecker_name: ClassVar[str]

    @staticmethod
    @abstractmethod
    def exit_code(_: Iterable[Address]) -> int:
        pass

    @property
    def typecheck_results(self) -> TypecheckResults:
        addresses = [config.address for config in self.field_sets]
        return TypecheckResults(
            [TypecheckResult(self.exit_code(addresses), "", "",)],
            typechecker_name=self.typechecker_name,
        )


class SuccessfulRequest(MockTypecheckRequest):
    typechecker_name = "SuccessfulTypechecker"

    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return 0


class FailingRequest(MockTypecheckRequest):
    typechecker_name = "FailingTypechecker"

    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return 1


class ConditionallySucceedsRequest(MockTypecheckRequest):
    typechecker_name = "ConditionallySucceedsTypechecker"

    @staticmethod
    def exit_code(addresses: Iterable[Address]) -> int:
        if any(address.target_name == "bad" for address in addresses):
            return 127
        return 0


class SkippedRequest(MockTypecheckRequest):
    @staticmethod
    def exit_code(_) -> int:
        return 0

    @property
    def typecheck_results(self) -> TypecheckResults:
        return TypecheckResults([], typechecker_name="SkippedTypechecker")


class InvalidField(Sources):
    pass


class InvalidFieldSet(MockTypecheckFieldSet):
    required_fields = (InvalidField,)


class InvalidRequest(MockTypecheckRequest):
    field_set_type = InvalidFieldSet
    typechecker_name = "InvalidTypechecker"

    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return -1


class TypecheckTest(TestBase):
    @staticmethod
    def make_target_with_origin(address: Optional[Address] = None) -> TargetWithOrigin:
        if address is None:
            address = Address.parse(":tests")
        return TargetWithOrigin(
            MockTarget({}, address=address),
            origin=AddressLiteralSpec(address.spec_path, address.target_name),
        )

    @staticmethod
    def run_typecheck_rule(
        *,
        request_types: List[Type[TypecheckRequest]],
        targets: List[TargetWithOrigin],
        include_sources: bool = True,
    ) -> Tuple[int, str]:
        console = MockConsole(use_colors=False)
        union_membership = UnionMembership({TypecheckRequest: request_types})
        result: Typecheck = run_rule(
            typecheck,
            rule_args=[console, TargetsWithOrigins(targets), union_membership],
            mock_gets=[
                MockGet(
                    product_type=TypecheckResults,
                    subject_type=TypecheckRequest,
                    mock=lambda field_set_collection: field_set_collection.typecheck_results,
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
        exit_code, stderr = self.run_typecheck_rule(
            request_types=[FailingRequest],
            targets=[self.make_target_with_origin()],
            include_sources=False,
        )
        assert exit_code == 0
        assert stderr == ""

    def test_invalid_target_noops(self) -> None:
        exit_code, stderr = self.run_typecheck_rule(
            request_types=[InvalidRequest], targets=[self.make_target_with_origin()]
        )
        assert exit_code == 0
        assert stderr == ""

    def test_summary(self) -> None:
        good_address = Address.parse(":good")
        bad_address = Address.parse(":bad")
        exit_code, stderr = self.run_typecheck_rule(
            request_types=[
                ConditionallySucceedsRequest,
                FailingRequest,
                SkippedRequest,
                SuccessfulRequest,
            ],
            targets=[
                self.make_target_with_origin(good_address),
                self.make_target_with_origin(bad_address),
            ],
        )
        assert exit_code == FailingRequest.exit_code([bad_address])
        assert stderr == dedent(
            """\

            𐄂 ConditionallySucceedsTypechecker failed.
            𐄂 FailingTypechecker failed.
            - SkippedTypechecker skipped.
            ✓ SuccessfulTypechecker succeeded.
            """
        )


def test_streaming_output_skip() -> None:
    results = TypecheckResults([], typechecker_name="typchecker")
    assert results.level() == LogLevel.DEBUG
    assert results.message() == "skipped."


def test_streaming_output_success() -> None:
    results = TypecheckResults(
        [TypecheckResult(0, "stdout", "stderr")], typechecker_name="typchecker"
    )
    assert results.level() == LogLevel.INFO
    assert results.message() == dedent(
        """\
        succeeded.
        stdout
        stderr

        """
    )


def test_streaming_output_failure() -> None:
    results = TypecheckResults(
        [TypecheckResult(18, "stdout", "stderr")], typechecker_name="typchecker"
    )
    assert results.level() == LogLevel.WARN
    assert results.message() == dedent(
        """\
        failed (exit code 18).
        stdout
        stderr

        """
    )


def test_streaming_output_partitions() -> None:
    results = TypecheckResults(
        [
            TypecheckResult(21, "", "", partition_description="ghc8.1"),
            TypecheckResult(0, "stdout", "stderr", partition_description="ghc9.2"),
        ],
        typechecker_name="typchecker",
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
