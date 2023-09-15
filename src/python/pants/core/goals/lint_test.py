# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Any, Iterable, Optional, Tuple, Type, TypeVar

import pytest

from pants.base.specs import Specs
from pants.core.goals.fix import FixFilesRequest, FixTargetsRequest
from pants.core.goals.fmt import FmtFilesRequest, FmtTargetsRequest
from pants.core.goals.lint import (
    AbstractLintRequest,
    Lint,
    LintFilesRequest,
    LintResult,
    LintSubsystem,
    LintTargetsRequest,
    Partitions,
    lint,
)
from pants.core.util_rules.distdir import DistDir
from pants.core.util_rules.environments import EnvironmentNameRequest
from pants.core.util_rules.partitions import PartitionerType, _EmptyMetadata
from pants.engine.addresses import Address
from pants.engine.environment import EnvironmentName
from pants.engine.fs import PathGlobs, SpecsPaths, Workspace
from pants.engine.internals.native_engine import EMPTY_SNAPSHOT, Snapshot
from pants.engine.rules import QueryRule
from pants.engine.target import Field, FieldSet, FilteredTargets, MultipleSourcesField, Target
from pants.engine.unions import UnionMembership
from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem
from pants.testutil.option_util import create_goal_subsystem
from pants.testutil.rule_runner import MockGet, RuleRunner, mock_console, run_rule_with_mocks
from pants.util.logging import LogLevel
from pants.util.meta import classproperty

_LintRequestT = TypeVar("_LintRequestT", bound=AbstractLintRequest)


class MockMultipleSourcesField(MultipleSourcesField):
    pass


class MockRequiredField(Field):
    alias = "required"
    required = True


class MockTarget(Target):
    alias = "mock_target"
    core_fields = (MockMultipleSourcesField, MockRequiredField)


@dataclass(frozen=True)
class MockLinterFieldSet(FieldSet):
    required_fields = (MultipleSourcesField,)
    sources: MultipleSourcesField
    required: MockRequiredField


class MockLintRequest(AbstractLintRequest, metaclass=ABCMeta):
    @staticmethod
    @abstractmethod
    def exit_code(_: Iterable[Address]) -> int:
        pass

    @classmethod
    @abstractmethod
    def get_lint_result(cls, elements: Iterable) -> LintResult:
        pass


class MockLintTargetsRequest(MockLintRequest, LintTargetsRequest):
    field_set_type = MockLinterFieldSet

    @classmethod
    def get_lint_result(cls, field_sets: Iterable[MockLinterFieldSet]) -> LintResult:
        addresses = [field_set.address for field_set in field_sets]
        return LintResult(cls.exit_code(addresses), "", "", cls.tool_name)


class SuccessfulRequest(MockLintTargetsRequest):
    @classproperty
    def tool_name(cls) -> str:
        return "Successful Linter"

    @classproperty
    def tool_id(cls) -> str:
        return "successfullinter"

    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return 0


class FailingRequest(MockLintTargetsRequest):
    @classproperty
    def tool_name(cls) -> str:
        return "Failing Linter"

    @classproperty
    def tool_id(cls) -> str:
        return "failinglinter"

    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return 1


class ConditionallySucceedsRequest(MockLintTargetsRequest):
    @classproperty
    def tool_name(cls) -> str:
        return "Conditionally Succeeds Linter"

    @classproperty
    def tool_id(cls) -> str:
        return "conditionallysucceedslinter"

    @staticmethod
    def exit_code(addresses: Iterable[Address]) -> int:
        if any(address.target_name == "bad" for address in addresses):
            return 127
        return 0


class SkippedRequest(MockLintTargetsRequest):
    @classproperty
    def tool_name(cls) -> str:
        return "Skipped Linter"

    @classproperty
    def tool_id(cls) -> str:
        return "skippedlinter"

    @staticmethod
    def exit_code(_) -> int:
        return 0


class InvalidField(MultipleSourcesField):
    pass


class InvalidFieldSet(MockLinterFieldSet):
    required_fields = (InvalidField,)


class InvalidRequest(MockLintTargetsRequest):
    field_set_type = InvalidFieldSet

    @classproperty
    def tool_name(cls) -> str:
        return "Invalid Linter"

    @classproperty
    def tool_id(cls) -> str:
        return "invalidlinter"

    @staticmethod
    def exit_code(_: Iterable[Address]) -> int:
        return -1


def _all_lint_requests() -> Iterable[type[MockLintRequest]]:
    classes = [MockLintRequest]
    while classes:
        cls = classes.pop()
        subclasses = cls.__subclasses__()
        classes.extend(subclasses)
        yield from subclasses


def mock_target_partitioner(
    request: MockLintTargetsRequest.PartitionRequest,
) -> Partitions[MockLinterFieldSet, Any]:
    if type(request) is SkippedRequest.PartitionRequest:
        return Partitions()

    operates_on_paths = {
        getattr(cls, "PartitionRequest"): cls._requires_snapshot for cls in _all_lint_requests()
    }[type(request)]
    if operates_on_paths:
        return Partitions.single_partition(fs.sources.globs for fs in request.field_sets)

    return Partitions.single_partition(request.field_sets)


class MockFilesRequest(MockLintRequest, LintFilesRequest):
    @classproperty
    def tool_name(cls) -> str:
        return "Files Linter"

    @classproperty
    def tool_id(cls) -> str:
        return "fileslinter"

    @classmethod
    def get_lint_result(cls, files: Iterable[str]) -> LintResult:
        return LintResult(0, "", "", cls.tool_name)


def mock_file_partitioner(request: MockFilesRequest.PartitionRequest) -> Partitions[str, Any]:
    return Partitions.single_partition(request.files)


def mock_lint_partition(request: Any) -> LintResult:
    request_type = {cls.Batch: cls for cls in _all_lint_requests()}[type(request)]
    return request_type.get_lint_result(request.elements)


class MockFmtRequest(MockLintRequest, FmtTargetsRequest):
    field_set_type = MockLinterFieldSet


class SuccessfulFormatter(MockFmtRequest):
    @classproperty
    def tool_name(cls) -> str:
        return "Successful Formatter"

    @classproperty
    def tool_id(cls) -> str:
        return "successfulformatter"

    @classmethod
    def get_lint_result(cls, field_sets: Iterable[MockLinterFieldSet]) -> LintResult:
        return LintResult(0, "", "", cls.tool_name)


class FailingFormatter(MockFmtRequest):
    @classproperty
    def tool_name(cls) -> str:
        return "Failing Formatter"

    @classproperty
    def tool_id(cls) -> str:
        return "failingformatter"

    @classmethod
    def get_lint_result(cls, field_sets: Iterable[MockLinterFieldSet]) -> LintResult:
        return LintResult(1, "", "", cls.tool_name)


class BuildFileFormatter(MockLintRequest, FmtFilesRequest):
    @classproperty
    def tool_name(cls) -> str:
        return "Bob The BUILDer"

    @classproperty
    def tool_id(cls) -> str:
        return "bob"

    @classmethod
    def get_lint_result(cls, files: Iterable[str]) -> LintResult:
        return LintResult(0, "", "", cls.tool_name)


class MockFixRequest(MockLintRequest, FixTargetsRequest):
    field_set_type = MockLinterFieldSet


class SuccessfulFixer(MockFixRequest):
    @classproperty
    def tool_name(cls) -> str:
        return "Successful Fixer"

    @classproperty
    def tool_id(cls) -> str:
        return "successfulfixer"

    @classmethod
    def get_lint_result(cls, field_sets: Iterable[MockLinterFieldSet]) -> LintResult:
        return LintResult(0, "", "", cls.tool_name)


class FailingFixer(MockFixRequest):
    @classproperty
    def tool_name(cls) -> str:
        return "Failing Fixer"

    @classproperty
    def tool_id(cls) -> str:
        return "failingfixer"

    @classmethod
    def get_lint_result(cls, field_sets: Iterable[MockLinterFieldSet]) -> LintResult:
        return LintResult(1, "", "", cls.tool_name)


class BuildFileFixer(MockLintRequest, FixFilesRequest):
    @classproperty
    def tool_name(cls) -> str:
        return "BUILD Annually"

    @classproperty
    def tool_id(cls) -> str:
        return "buildannually"

    @classmethod
    def get_lint_result(cls, files: Iterable[str]) -> LintResult:
        return LintResult(0, "", "", cls.tool_name)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner()


def make_target(address: Optional[Address] = None) -> Target:
    return MockTarget(
        {MockRequiredField.alias: "present"}, address or Address("", target_name="tests")
    )


def run_lint_rule(
    rule_runner: RuleRunner,
    *,
    lint_request_types: Iterable[Type[_LintRequestT]],
    targets: list[Target],
    batch_size: int = 128,
    only: list[str] | None = None,
    skip_formatters: bool = False,
    skip_fixers: bool = False,
) -> Tuple[int, str]:
    union_membership = UnionMembership(
        {
            AbstractLintRequest: lint_request_types,
            AbstractLintRequest.Batch: [rt.Batch for rt in lint_request_types],
            LintTargetsRequest.PartitionRequest: [
                rt.PartitionRequest
                for rt in lint_request_types
                if issubclass(rt, LintTargetsRequest)
            ],
            LintFilesRequest.PartitionRequest: [
                rt.PartitionRequest for rt in lint_request_types if issubclass(rt, LintFilesRequest)
            ],
        }
    )
    lint_subsystem = create_goal_subsystem(
        LintSubsystem,
        batch_size=batch_size,
        only=only or [],
        skip_formatters=skip_formatters,
        skip_fixers=skip_fixers,
    )
    with mock_console(rule_runner.options_bootstrapper) as (console, stdio_reader):
        result: Lint = run_rule_with_mocks(
            lint,
            rule_args=[
                console,
                Workspace(rule_runner.scheduler, _enforce_effects=False),
                Specs.empty(),
                lint_subsystem,
                union_membership,
                DistDir(relpath=Path("dist")),
            ],
            mock_gets=[
                MockGet(
                    output_type=Partitions,
                    input_types=(LintTargetsRequest.PartitionRequest,),
                    mock=mock_target_partitioner,
                ),
                MockGet(
                    output_type=EnvironmentName,
                    input_types=(EnvironmentNameRequest,),
                    mock=lambda _: EnvironmentName(None),
                ),
                MockGet(
                    output_type=Partitions,
                    input_types=(LintFilesRequest.PartitionRequest,),
                    mock=mock_file_partitioner,
                ),
                MockGet(
                    output_type=LintResult,
                    input_types=(AbstractLintRequest.Batch,),
                    mock=mock_lint_partition,
                ),
                MockGet(
                    output_type=FilteredTargets,
                    input_types=(Specs,),
                    mock=lambda _: FilteredTargets(tuple(targets)),
                ),
                MockGet(
                    output_type=SpecsPaths,
                    input_types=(Specs,),
                    mock=lambda _: SpecsPaths(("f.txt", "BUILD"), ()),
                ),
                MockGet(
                    output_type=Snapshot,
                    input_types=(PathGlobs,),
                    mock=lambda _: EMPTY_SNAPSHOT,
                ),
            ],
            union_membership=union_membership,
        )
        assert not stdio_reader.get_stdout()
        return result.exit_code, stdio_reader.get_stderr()


def test_duplicate_files_in_fixer(rule_runner: RuleRunner) -> None:
    assert MockFixRequest.Batch(
        "tool_name",
        ("a", "a"),
        _EmptyMetadata(),
        rule_runner.make_snapshot({"a": ""}),
    ).files == ("a",)


def test_invalid_target_noops(rule_runner: RuleRunner) -> None:
    exit_code, stderr = run_lint_rule(
        rule_runner, lint_request_types=[InvalidRequest], targets=[make_target()]
    )
    assert exit_code == 0
    assert stderr == ""


def test_summary(rule_runner: RuleRunner) -> None:
    """Test that we render the summary correctly.

    This tests that we:
    * Merge multiple results belonging to the same linter (`--per-file-caching`).
    * Decide correctly between skipped, failed, and succeeded.
    """
    good_address = Address("", target_name="good")
    bad_address = Address("", target_name="bad")

    request_types = [
        ConditionallySucceedsRequest,
        FailingRequest,
        SkippedRequest,
        SuccessfulRequest,
        SuccessfulFormatter,
        FailingFormatter,
        BuildFileFormatter,
        SuccessfulFixer,
        FailingFixer,
        BuildFileFixer,
        MockFilesRequest,
    ]
    targets = [make_target(good_address), make_target(bad_address)]

    exit_code, stderr = run_lint_rule(
        rule_runner,
        lint_request_types=request_types,
        targets=targets,
    )
    assert exit_code == FailingRequest.exit_code([bad_address])
    assert stderr == dedent(
        """\

        ✓ BUILD Annually succeeded.
        ✓ Bob The BUILDer succeeded.
        ✕ Conditionally Succeeds Linter failed.
        ✕ Failing Fixer failed.
        ✕ Failing Formatter failed.
        ✕ Failing Linter failed.
        ✓ Files Linter succeeded.
        ✓ Successful Fixer succeeded.
        ✓ Successful Formatter succeeded.
        ✓ Successful Linter succeeded.

        (One or more formatters failed. Run `pants fmt` to fix.)
        (One or more fixers failed. Run `pants fix` to fix.)
        """
    )

    exit_code, stderr = run_lint_rule(
        rule_runner,
        lint_request_types=request_types,
        targets=targets,
        only=[
            FailingRequest.tool_id,
            MockFilesRequest.tool_id,
            FailingFormatter.tool_id,
            FailingFixer.tool_id,
            BuildFileFormatter.tool_id,
            BuildFileFixer.tool_id,
        ],
    )
    assert stderr == dedent(
        """\

        ✓ BUILD Annually succeeded.
        ✓ Bob The BUILDer succeeded.
        ✕ Failing Fixer failed.
        ✕ Failing Formatter failed.
        ✕ Failing Linter failed.
        ✓ Files Linter succeeded.

        (One or more formatters failed. Run `pants fmt` to fix.)
        (One or more fixers failed. Run `pants fix` to fix.)
        """
    )

    exit_code, stderr = run_lint_rule(
        rule_runner,
        lint_request_types=request_types,
        targets=targets,
        skip_formatters=True,
        skip_fixers=True,
    )
    assert stderr == dedent(
        """\

        ✕ Conditionally Succeeds Linter failed.
        ✕ Failing Linter failed.
        ✓ Files Linter succeeded.
        ✓ Successful Linter succeeded.
        """
    )

    exit_code, stderr = run_lint_rule(
        rule_runner,
        lint_request_types=request_types,
        targets=targets,
        skip_fixers=True,
    )
    assert stderr == dedent(
        """\

        ✓ Bob The BUILDer succeeded.
        ✕ Conditionally Succeeds Linter failed.
        ✕ Failing Formatter failed.
        ✕ Failing Linter failed.
        ✓ Files Linter succeeded.
        ✓ Successful Formatter succeeded.
        ✓ Successful Linter succeeded.

        (One or more formatters failed. Run `pants fmt` to fix.)
        """
    )

    exit_code, stderr = run_lint_rule(
        rule_runner,
        lint_request_types=request_types,
        targets=targets,
        skip_formatters=True,
    )
    assert stderr == dedent(
        """\

        ✓ BUILD Annually succeeded.
        ✕ Conditionally Succeeds Linter failed.
        ✕ Failing Fixer failed.
        ✕ Failing Linter failed.
        ✓ Files Linter succeeded.
        ✓ Successful Fixer succeeded.
        ✓ Successful Linter succeeded.

        (One or more fixers failed. Run `pants fix` to fix.)
        """
    )


def test_default_single_partition_partitioner() -> None:
    class KitchenSubsystem(Subsystem):
        options_scope = "kitchen"
        help = "a cookbook might help"
        name = "The Kitchen"
        skip = SkipOption("lint")

    class LintKitchenRequest(LintTargetsRequest):
        field_set_type = MockLinterFieldSet
        tool_subsystem = KitchenSubsystem
        partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION

    rules = [
        *LintKitchenRequest._get_rules(),
        QueryRule(Partitions, [LintKitchenRequest.PartitionRequest]),
    ]
    rule_runner = RuleRunner(rules=rules)
    field_sets = (
        MockLinterFieldSet(
            Address("knife"),
            MultipleSourcesField(["knife"], Address("knife")),
            MockRequiredField("present", Address("")),
        ),
        MockLinterFieldSet(
            Address("bowl"),
            MultipleSourcesField(["bowl"], Address("bowl")),
            MockRequiredField("present", Address("")),
        ),
    )
    partitions = rule_runner.request(Partitions, [LintKitchenRequest.PartitionRequest(field_sets)])
    assert len(partitions) == 1
    assert partitions[0].elements == field_sets

    rule_runner.set_options(["--kitchen-skip"])
    partitions = rule_runner.request(Partitions, [LintKitchenRequest.PartitionRequest(field_sets)])
    assert partitions == Partitions([])


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

        ✓ Conditionally Succeeds Linter succeeded.
        ✕ Failing Linter failed.
        ✓ Successful Linter succeeded.
        """
    )


def test_streaming_output_success() -> None:
    result = LintResult(0, "stdout", "stderr", linter_name="linter")
    assert result.level() == LogLevel.INFO
    assert result.message() == dedent(
        """\
        linter succeeded.
        stdout
        stderr

        """
    )


def test_streaming_output_failure() -> None:
    result = LintResult(18, "stdout", "stderr", linter_name="linter")
    assert result.level() == LogLevel.ERROR
    assert result.message() == dedent(
        """\
        linter failed (exit code 18).
        stdout
        stderr

        """
    )


def test_streaming_output_partitions() -> None:
    result = LintResult(
        21, "stdout", "stderr", linter_name="linter", partition_description="ghc9.2"
    )
    assert result.level() == LogLevel.ERROR
    assert result.message() == dedent(
        """\
        linter failed (exit code 21).
        Partition: ghc9.2
        stdout
        stderr

        """
    )
