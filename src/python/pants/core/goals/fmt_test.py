# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta, abstractmethod
from pathlib import Path
from textwrap import dedent
from typing import ClassVar, List, Optional, Type

import pytest

from pants.core.goals.fmt import (
    Fmt,
    FmtResult,
    FmtSubsystem,
    LanguageFmtResults,
    LanguageFmtTargets,
    fmt,
)
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST, Digest, FileContent, MergeDigests, Workspace
from pants.engine.target import MultipleSourcesField, Target, Targets
from pants.engine.unions import UnionMembership
from pants.testutil.option_util import create_goal_subsystem
from pants.testutil.rule_runner import MockGet, RuleRunner, mock_console, run_rule_with_mocks
from pants.util.logging import LogLevel


class FortranSources(MultipleSourcesField):
    pass


class FortranTarget(Target):
    alias = "fortran"
    core_fields = (FortranSources,)


class SmalltalkSources(MultipleSourcesField):
    pass


class SmalltalkTarget(Target):
    alias = "smalltalk"
    core_fields = (SmalltalkSources,)


class InvalidSources(MultipleSourcesField):
    pass


class MockLanguageTargets(LanguageFmtTargets, metaclass=ABCMeta):
    formatter_name: ClassVar[str]

    @abstractmethod
    def language_fmt_results(self, result_digest: Digest) -> LanguageFmtResults:
        pass


class FortranTargets(MockLanguageTargets):
    required_fields = (FortranSources,)

    def language_fmt_results(self, result_digest: Digest) -> LanguageFmtResults:
        output = (
            result_digest
            if any(tgt.address.target_name == "needs_formatting" for tgt in self.targets)
            else EMPTY_DIGEST
        )
        return LanguageFmtResults(
            (
                FmtResult(
                    input=EMPTY_DIGEST,
                    output=output,
                    stdout="",
                    stderr="",
                    formatter_name="FortranConditionallyDidChange",
                ),
            ),
            input=EMPTY_DIGEST,
            output=result_digest,
        )


class SmalltalkTargets(MockLanguageTargets):
    required_fields = (SmalltalkSources,)

    def language_fmt_results(self, result_digest: Digest) -> LanguageFmtResults:
        return LanguageFmtResults(
            (
                FmtResult(
                    input=result_digest,
                    output=result_digest,
                    stdout="",
                    stderr="",
                    formatter_name="SmalltalkDidNotChange",
                ),
                FmtResult.skip(formatter_name="SmalltalkSkipped"),
            ),
            input=EMPTY_DIGEST,
            output=result_digest,
        )


class InvalidTargets(MockLanguageTargets):
    required_fields = (InvalidSources,)

    def language_fmt_results(self, result_digest: Digest) -> LanguageFmtResults:
        # Note: we return a result that would result in a change so that we can validate that this
        # result is not actually returned.
        return LanguageFmtResults(
            (
                FmtResult(
                    input=EMPTY_DIGEST,
                    output=result_digest,
                    stdout="",
                    stderr="",
                    formatter_name="InvalidFormatter",
                ),
            ),
            input=EMPTY_DIGEST,
            output=result_digest,
        )


FORTRAN_FILE = FileContent("formatted.f98", b"READ INPUT TAPE 5\n")
SMALLTALK_FILE = FileContent("formatted.st", b"y := self size + super size.')\n")


@pytest.fixture
def rule_runner() -> RuleRunner:
    # While we use `run_rule_with_mocks`, rather than `RuleRunner.request()`, we still need an
    # instance of a Scheduler.
    return RuleRunner()


def fortran_digest(rule_runner: RuleRunner) -> Digest:
    return rule_runner.make_snapshot({FORTRAN_FILE.path: FORTRAN_FILE.content.decode()}).digest


def merged_digest(rule_runner: RuleRunner) -> Digest:
    return rule_runner.make_snapshot(
        {fc.path: fc.content.decode() for fc in (FORTRAN_FILE, SMALLTALK_FILE)}
    ).digest


def make_target(
    address: Optional[Address] = None, *, target_cls: Type[Target] = FortranTarget
) -> Target:
    return target_cls({}, address or Address("", target_name="tests"))


def run_fmt_rule(
    rule_runner: RuleRunner,
    *,
    language_target_collection_types: List[Type[LanguageFmtTargets]],
    targets: List[Target],
    result_digest: Digest,
    per_file_caching: bool,
) -> str:
    with mock_console(rule_runner.options_bootstrapper) as (console, stdio_reader):
        union_membership = UnionMembership({LanguageFmtTargets: language_target_collection_types})
        result: Fmt = run_rule_with_mocks(
            fmt,
            rule_args=[
                console,
                Targets(targets),
                create_goal_subsystem(
                    FmtSubsystem, per_file_caching=per_file_caching, per_target_caching=False
                ),
                Workspace(rule_runner.scheduler, _enforce_effects=False),
                union_membership,
            ],
            mock_gets=[
                MockGet(
                    output_type=LanguageFmtResults,
                    input_type=LanguageFmtTargets,
                    mock=lambda language_targets_collection: language_targets_collection.language_fmt_results(
                        result_digest
                    ),
                ),
                MockGet(
                    output_type=Digest,
                    input_type=MergeDigests,
                    mock=lambda _: result_digest,
                ),
            ],
            union_membership=union_membership,
        )
        assert result.exit_code == 0
        assert not stdio_reader.get_stdout()
        return stdio_reader.get_stderr()


def assert_workspace_modified(
    rule_runner: RuleRunner, *, fortran_formatted: bool, smalltalk_formatted: bool
) -> None:
    fortran_file = Path(rule_runner.build_root, FORTRAN_FILE.path)
    smalltalk_file = Path(rule_runner.build_root, SMALLTALK_FILE.path)
    if fortran_formatted:
        assert fortran_file.is_file()
        assert fortran_file.read_text() == FORTRAN_FILE.content.decode()
    if smalltalk_formatted:
        assert smalltalk_file.is_file()
        assert smalltalk_file.read_text() == SMALLTALK_FILE.content.decode()


def test_invalid_target_noops(rule_runner: RuleRunner) -> None:
    def assert_noops(*, per_file_caching: bool) -> None:
        stderr = run_fmt_rule(
            rule_runner,
            language_target_collection_types=[InvalidTargets],
            targets=[make_target()],
            result_digest=fortran_digest(rule_runner),
            per_file_caching=per_file_caching,
        )
        assert stderr.strip() == ""
        assert_workspace_modified(rule_runner, fortran_formatted=False, smalltalk_formatted=False)

    assert_noops(per_file_caching=False)
    assert_noops(per_file_caching=True)


def test_summary(rule_runner: RuleRunner) -> None:
    """Tests that the final summary is correct.

    This checks that we:
    * Merge multiple results for the same formatter together (when you use
        `--per-file-caching`).
    * Correctly distinguish between skipped, changed, and did not change.
    """
    fortran_addresses = [
        Address("", target_name="f1"),
        Address("", target_name="needs_formatting"),
    ]
    smalltalk_addresses = [Address("", target_name="s1"), Address("", target_name="s2")]

    fortran_targets = [make_target(addr, target_cls=FortranTarget) for addr in fortran_addresses]
    smalltalk_targets = [
        make_target(addr, target_cls=SmalltalkTarget) for addr in smalltalk_addresses
    ]

    def assert_expected(*, per_file_caching: bool) -> None:
        stderr = run_fmt_rule(
            rule_runner,
            language_target_collection_types=[FortranTargets, SmalltalkTargets],
            targets=[*fortran_targets, *smalltalk_targets],
            result_digest=merged_digest(rule_runner),
            per_file_caching=per_file_caching,
        )
        assert_workspace_modified(rule_runner, fortran_formatted=True, smalltalk_formatted=True)
        assert stderr == dedent(
            """\

            + FortranConditionallyDidChange made changes.
            ✓ SmalltalkDidNotChange made no changes.
            - SmalltalkSkipped skipped.
            """
        )

    assert_expected(per_file_caching=False)
    assert_expected(per_file_caching=True)


def test_streaming_output_skip() -> None:
    result = FmtResult.skip(formatter_name="formatter")
    assert result.level() == LogLevel.DEBUG
    assert result.message() == "formatter skipped."


def test_streaming_output_changed() -> None:
    changed_digest = Digest(EMPTY_DIGEST.fingerprint, 2)
    result = FmtResult(
        input=EMPTY_DIGEST,
        output=changed_digest,
        stdout="stdout",
        stderr="stderr",
        formatter_name="formatter",
    )
    assert result.level() == LogLevel.WARN
    assert result.message() == dedent(
        """\
        formatter made changes.
        stdout
        stderr

        """
    )


def test_streaming_output_not_changed() -> None:
    result = FmtResult(
        input=EMPTY_DIGEST,
        output=EMPTY_DIGEST,
        stdout="stdout",
        stderr="stderr",
        formatter_name="formatter",
    )
    assert result.level() == LogLevel.INFO
    assert result.message() == dedent(
        """\
        formatter made no changes.
        stdout
        stderr

        """
    )
