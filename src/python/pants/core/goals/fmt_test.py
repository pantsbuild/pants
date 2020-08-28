# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta, abstractmethod
from pathlib import Path
from textwrap import dedent
from typing import ClassVar, List, Optional, Type, cast

from pants.core.goals.fmt import (
    Fmt,
    FmtResult,
    FmtSubsystem,
    LanguageFmtResults,
    LanguageFmtTargets,
    fmt,
)
from pants.core.util_rules.filter_empty_sources import TargetsWithSources, TargetsWithSourcesRequest
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST, Digest, FileContent, MergeDigests, Workspace
from pants.engine.target import Sources, Target, Targets
from pants.engine.unions import UnionMembership
from pants.testutil.engine_util import MockConsole, MockGet, run_rule
from pants.testutil.option_util import create_goal_subsystem
from pants.testutil.test_base import TestBase
from pants.util.logging import LogLevel


class FortranSources(Sources):
    pass


class FortranTarget(Target):
    alias = "fortran"
    core_fields = (FortranSources,)


class SmalltalkSources(Sources):
    pass


class SmalltalkTarget(Target):
    alias = "smalltalk"
    core_fields = (SmalltalkSources,)


class InvalidSources(Sources):
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


class FmtTest(TestBase):
    def setUp(self) -> None:
        super().setUp()
        self.fortran_file = FileContent("formatted.f98", b"READ INPUT TAPE 5\n")
        self.smalltalk_file = FileContent("formatted.st", b"y := self size + super size.')\n")
        self.fortran_digest = self.make_snapshot(
            {self.fortran_file.path: self.fortran_file.content.decode()}
        ).digest
        self.merged_digest = self.make_snapshot(
            {fc.path: fc.content.decode() for fc in (self.fortran_file, self.smalltalk_file)}
        ).digest

    @staticmethod
    def make_target(
        address: Optional[Address] = None, *, target_cls: Type[Target] = FortranTarget
    ) -> Target:
        return target_cls({}, address=address or Address.parse(":tests"))

    def run_fmt_rule(
        self,
        *,
        language_target_collection_types: List[Type[LanguageFmtTargets]],
        targets: List[Target],
        result_digest: Digest,
        per_file_caching: bool,
        include_sources: bool = True,
    ) -> str:
        console = MockConsole(use_colors=False)
        union_membership = UnionMembership({LanguageFmtTargets: language_target_collection_types})
        result: Fmt = run_rule(
            fmt,
            rule_args=[
                console,
                Targets(targets),
                create_goal_subsystem(
                    FmtSubsystem, per_file_caching=per_file_caching, per_target_caching=False
                ),
                Workspace(self.scheduler),
                union_membership,
            ],
            mock_gets=[
                MockGet(
                    product_type=LanguageFmtResults,
                    subject_type=LanguageFmtTargets,
                    mock=lambda language_targets_collection: language_targets_collection.language_fmt_results(
                        result_digest
                    ),
                ),
                MockGet(
                    product_type=TargetsWithSources,
                    subject_type=TargetsWithSourcesRequest,
                    mock=lambda tgts: TargetsWithSources(tgts if include_sources else ()),
                ),
                MockGet(
                    product_type=Digest,
                    subject_type=MergeDigests,
                    mock=lambda _: result_digest,
                ),
            ],
            union_membership=union_membership,
        )
        assert result.exit_code == 0
        assert not console.stdout.getvalue()
        return cast(str, console.stderr.getvalue())

    def assert_workspace_modified(
        self, *, fortran_formatted: bool, smalltalk_formatted: bool
    ) -> None:
        fortran_file = Path(self.build_root, self.fortran_file.path)
        smalltalk_file = Path(self.build_root, self.smalltalk_file.path)
        if fortran_formatted:
            assert fortran_file.is_file()
            assert fortran_file.read_text() == self.fortran_file.content.decode()
        if smalltalk_formatted:
            assert smalltalk_file.is_file()
            assert smalltalk_file.read_text() == self.smalltalk_file.content.decode()

    def test_empty_target_noops(self) -> None:
        def assert_noops(*, per_file_caching: bool) -> None:
            stderr = self.run_fmt_rule(
                language_target_collection_types=[FortranTargets],
                targets=[self.make_target()],
                result_digest=self.fortran_digest,
                per_file_caching=per_file_caching,
                include_sources=False,
            )
            assert stderr.strip() == ""
            self.assert_workspace_modified(fortran_formatted=False, smalltalk_formatted=False)

        assert_noops(per_file_caching=False)
        assert_noops(per_file_caching=True)

    def test_invalid_target_noops(self) -> None:
        def assert_noops(*, per_file_caching: bool) -> None:
            stderr = self.run_fmt_rule(
                language_target_collection_types=[InvalidTargets],
                targets=[self.make_target()],
                result_digest=self.fortran_digest,
                per_file_caching=per_file_caching,
            )
            assert stderr.strip() == ""
            self.assert_workspace_modified(fortran_formatted=False, smalltalk_formatted=False)

        assert_noops(per_file_caching=False)
        assert_noops(per_file_caching=True)

    def test_summary(self) -> None:
        """Tests that the final summary is correct.

        This checks that we:
        * Merge multiple results for the same formatter together (when you use
            `--per-file-caching`).
        * Correctly distinguish between skipped, changed, and did not change.
        """
        fortran_addresses = [Address.parse(":f1"), Address.parse(":needs_formatting")]
        smalltalk_addresses = [Address.parse(":s1"), Address.parse(":s2")]

        fortran_targets = [
            self.make_target(addr, target_cls=FortranTarget) for addr in fortran_addresses
        ]
        smalltalk_targets = [
            self.make_target(addr, target_cls=SmalltalkTarget) for addr in smalltalk_addresses
        ]

        def assert_expected(*, per_file_caching: bool) -> None:
            stderr = self.run_fmt_rule(
                language_target_collection_types=[FortranTargets, SmalltalkTargets],
                targets=[*fortran_targets, *smalltalk_targets],
                result_digest=self.merged_digest,
                per_file_caching=per_file_caching,
            )
            self.assert_workspace_modified(fortran_formatted=True, smalltalk_formatted=True)
            assert stderr == dedent(
                """\

                𐄂 FortranConditionallyDidChange made changes.
                ✓ SmalltalkDidNotChange made no changes.
                - SmalltalkSkipped skipped.
                """
            )

        assert_expected(per_file_caching=False)
        assert_expected(per_file_caching=True)


def test_streaming_output_skip() -> None:
    result = FmtResult.skip(formatter_name="formatter")
    assert result.level() == LogLevel.DEBUG
    assert result.message() == "skipped."


def test_streaming_output_changed() -> None:
    result = FmtResult(
        input=EMPTY_DIGEST,
        output=Digest("abc", 10),
        stdout="stdout",
        stderr="stderr",
        formatter_name="formatter",
    )
    assert result.level() == LogLevel.WARN
    assert result.message() == dedent(
        """\
        made changes.
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
        made no changes.
        stdout
        stderr

        """
    )
