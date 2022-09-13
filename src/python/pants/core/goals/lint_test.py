# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Iterable, Optional, Sequence, Tuple, Type

import pytest

from pants.base.specs import Specs
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest, _FmtBuildFilesRequest
from pants.core.goals.lint import (
    AmbiguousRequestNamesError,
    Lint,
    LintFilesRequest,
    LintResult,
    LintResults,
    LintSubsystem,
    LintTargetsRequest,
    lint,
)
from pants.core.util_rules.distdir import DistDir
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import PathGlobs, SpecsPaths, Workspace
from pants.engine.internals.build_files import BuildFileOptions
from pants.engine.internals.native_engine import EMPTY_DIGEST, EMPTY_SNAPSHOT, Digest, Snapshot
from pants.engine.target import FieldSet, FilteredTargets, MultipleSourcesField, Target
from pants.engine.unions import UnionMembership
from pants.testutil.option_util import create_goal_subsystem
from pants.testutil.rule_runner import MockGet, RuleRunner, mock_console, run_rule_with_mocks
from pants.util.logging import LogLevel


class MockMultipleSourcesField(MultipleSourcesField):
    pass


class MockTarget(Target):
    alias = "mock_target"
    core_fields = (MockMultipleSourcesField,)


@dataclass(frozen=True)
class MockLinterFieldSet(FieldSet):
    required_fields = (MultipleSourcesField,)
    sources: MultipleSourcesField


class MockLintRequest(LintTargetsRequest, metaclass=ABCMeta):
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


class MockFmtRequest(FmtTargetsRequest):
    field_set_type = MockLinterFieldSet


class SuccessfulFormatter(MockFmtRequest):
    name = "SuccessfulFormatter"

    @property
    def fmt_result(self) -> FmtResult:
        return FmtResult(EMPTY_SNAPSHOT, EMPTY_SNAPSHOT, "", "", formatter_name=self.name)


class FailingFormatter(MockFmtRequest):
    name = "FailingFormatter"

    @property
    def fmt_result(self) -> FmtResult:
        before = EMPTY_SNAPSHOT
        after = Snapshot._unsafe_create(Digest(EMPTY_DIGEST.fingerprint, 2), [], [])
        return FmtResult(before, after, "", "", formatter_name=self.name)


class BuildFileFormatter(_FmtBuildFilesRequest):
    name = "BobTheBUILDer"

    @property
    def fmt_result(self) -> FmtResult:
        return FmtResult(EMPTY_SNAPSHOT, EMPTY_SNAPSHOT, "", "", formatter_name=self.name)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner()


def make_target(address: Optional[Address] = None) -> Target:
    return MockTarget({}, address or Address("", target_name="tests"))


def run_lint_rule(
    rule_runner: RuleRunner,
    *,
    lint_request_types: Sequence[Type[LintTargetsRequest]],
    fmt_request_types: Sequence[Type[FmtTargetsRequest]] = (),
    targets: list[Target],
    run_files_linter: bool = False,
    run_build_formatter: bool = False,
    batch_size: int = 128,
    only: list[str] | None = None,
    skip_formatters: bool = False,
) -> Tuple[int, str]:
    union_membership = UnionMembership(
        {
            LintTargetsRequest: lint_request_types,
            LintFilesRequest: [MockFilesRequest] if run_files_linter else [],
            _FmtBuildFilesRequest: [BuildFileFormatter] if run_build_formatter else [],
            FmtTargetsRequest: fmt_request_types,
        }
    )
    lint_subsystem = create_goal_subsystem(
        LintSubsystem,
        batch_size=batch_size,
        only=only or [],
        skip_formatters=skip_formatters,
    )
    with mock_console(rule_runner.options_bootstrapper) as (console, stdio_reader):
        result: Lint = run_rule_with_mocks(
            lint,
            rule_args=[
                console,
                Workspace(rule_runner.scheduler, _enforce_effects=False),
                Specs.empty(),
                BuildFileOptions(("BUILD",)),
                lint_subsystem,
                union_membership,
                DistDir(relpath=Path("dist")),
            ],
            mock_gets=[
                MockGet(
                    output_type=SourceFiles,
                    input_types=(SourceFilesRequest,),
                    mock=lambda _: SourceFiles(EMPTY_SNAPSHOT, ()),
                ),
                MockGet(
                    output_type=LintResults,
                    input_types=(LintTargetsRequest,),
                    mock=lambda mock_request: mock_request.lint_results,
                ),
                MockGet(
                    output_type=LintResults,
                    input_types=(LintFilesRequest,),
                    mock=lambda mock_request: mock_request.lint_results,
                ),
                MockGet(
                    output_type=FmtResult,
                    input_types=(FmtTargetsRequest,),
                    mock=lambda mock_request: mock_request.fmt_result,
                ),
                MockGet(
                    output_type=FmtResult,
                    input_types=(_FmtBuildFilesRequest,),
                    mock=lambda mock_request: mock_request.fmt_result,
                ),
                MockGet(
                    output_type=FilteredTargets,
                    input_types=(Specs,),
                    mock=lambda _: FilteredTargets(targets),
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

    lint_request_types = [
        ConditionallySucceedsRequest,
        FailingRequest,
        SkippedRequest,
        SuccessfulRequest,
    ]
    fmt_request_types = [
        SuccessfulFormatter,
        FailingFormatter,
    ]
    targets = [make_target(good_address), make_target(bad_address)]

    exit_code, stderr = run_lint_rule(
        rule_runner,
        lint_request_types=lint_request_types,
        fmt_request_types=fmt_request_types,
        targets=targets,
        run_files_linter=True,
        run_build_formatter=True,
    )
    assert exit_code == FailingRequest.exit_code([bad_address])
    assert stderr == dedent(
        """\

        ✓ BobTheBUILDer succeeded.
        ✕ ConditionallySucceedsLinter failed.
        ✕ FailingFormatter failed.
        ✕ FailingLinter failed.
        ✓ FilesLinter succeeded.
        ✓ SuccessfulFormatter succeeded.
        ✓ SuccessfulLinter succeeded.

        (One or more formatters failed. Run `./pants fmt` to fix.)
        """
    )

    exit_code, stderr = run_lint_rule(
        rule_runner,
        lint_request_types=lint_request_types,
        fmt_request_types=fmt_request_types,
        targets=targets,
        run_files_linter=True,
        run_build_formatter=True,
        only=[
            FailingRequest.name,
            MockFilesRequest.name,
            FailingFormatter.name,
            BuildFileFormatter.name,
        ],
    )
    assert stderr == dedent(
        """\

        ✓ BobTheBUILDer succeeded.
        ✕ FailingFormatter failed.
        ✕ FailingLinter failed.
        ✓ FilesLinter succeeded.

        (One or more formatters failed. Run `./pants fmt` to fix.)
        """
    )

    exit_code, stderr = run_lint_rule(
        rule_runner,
        lint_request_types=lint_request_types,
        fmt_request_types=fmt_request_types,
        targets=targets,
        run_files_linter=True,
        run_build_formatter=True,
        skip_formatters=True,
    )
    assert stderr == dedent(
        """\

        ✕ ConditionallySucceedsLinter failed.
        ✕ FailingLinter failed.
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
        ✕ FailingLinter failed.
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


def test_duplicated_names(rule_runner: RuleRunner) -> None:
    class AmbiguousLintTargetsRequest(LintTargetsRequest):
        name = "FilesLinter"  # also used by MockFilesRequest

    with pytest.raises(AmbiguousRequestNamesError):
        run_lint_rule(
            rule_runner,
            lint_request_types=[AmbiguousLintTargetsRequest],
            run_files_linter=True,  # needed for MockFilesRequest
            targets=[],
        )

    class BuildAndLintTargetType(LintTargetsRequest):
        name = BuildFileFormatter.name

    with pytest.raises(AmbiguousRequestNamesError):
        run_lint_rule(
            rule_runner,
            lint_request_types=[BuildAndLintTargetType],
            targets=[],
            run_build_formatter=True,
        )

    class BuildAndFmtTargetType(FmtTargetsRequest):
        name = BuildFileFormatter.name

    # Ambiguity between a target formatter and BUILD formatter are OK
    run_lint_rule(
        rule_runner,
        lint_request_types=[],
        fmt_request_types=[BuildAndFmtTargetType],
        run_build_formatter=True,
        targets=[],
    )
