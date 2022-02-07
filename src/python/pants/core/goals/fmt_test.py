# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import List, Type

import pytest

from pants.core.goals.fmt import Fmt, FmtRequest, FmtResult
from pants.core.goals.fmt import rules as fmt_rules
from pants.core.util_rules import source_files
from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Digest, FileContent
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import FieldSet, MultipleSourcesField, Target
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.logging import LogLevel

FORTRAN_FILE = FileContent("formatted.f98", b"READ INPUT TAPE 5\n")
SMALLTALK_FILE = FileContent("formatted.st", b"y := self size + super size.')\n")


class FortranSources(MultipleSourcesField):
    pass


class FortranTarget(Target):
    alias = "fortran"
    core_fields = (FortranSources,)


@dataclass(frozen=True)
class FortranFieldSet(FieldSet):
    required_fields = (FortranSources,)

    sources: FortranSources


class FortranFmtRequest(FmtRequest):
    field_set_type = FortranFieldSet
    name = "FortranConditionallyDidChange"


@rule
async def fortran_fmt(request: FortranFmtRequest) -> FmtResult:
    output = (
        await Get(Digest, CreateDigest([FORTRAN_FILE]))
        if any(fs.address.target_name == "needs_formatting" for fs in request.field_sets)
        else EMPTY_DIGEST
    )
    return FmtResult(
        input=EMPTY_DIGEST, output=output, stdout="", stderr="", formatter_name=request.name
    )


class SmalltalkSources(MultipleSourcesField):
    pass


class SmalltalkTarget(Target):
    alias = "smalltalk"
    core_fields = (SmalltalkSources,)


@dataclass(frozen=True)
class SmalltalkFieldSet(FieldSet):
    required_fields = (SmalltalkSources,)

    sources: SmalltalkSources


class SmalltalkNoopRequest(FmtRequest):
    field_set_type = SmalltalkFieldSet
    name = "SmalltalkDidNotChange"


@rule
async def smalltalk_noop(request: SmalltalkNoopRequest) -> FmtResult:
    result_digest = await Get(Digest, CreateDigest([SMALLTALK_FILE]))
    return FmtResult(
        input=result_digest,
        output=result_digest,
        stdout="",
        stderr="",
        formatter_name=request.name,
    )


class SmalltalkSkipRequest(FmtRequest):
    field_set_type = SmalltalkFieldSet
    name = "SmalltalkSkipped"


@rule
def smalltalk_skip(request: SmalltalkSkipRequest) -> FmtResult:
    return FmtResult.skip(formatter_name=request.name)


def fmt_rule_runner(
    target_types: List[Type[Target]],
    fmt_request_types: List[Type[FmtRequest]],
) -> RuleRunner:
    return RuleRunner(
        rules=[
            *collect_rules(),
            *source_files.rules(),
            *fmt_rules(),
            *(UnionRule(FmtRequest, frt) for frt in fmt_request_types),
        ],
        target_types=target_types,
    )


def fortran_digest(rule_runner: RuleRunner) -> Digest:
    return rule_runner.make_snapshot({FORTRAN_FILE.path: FORTRAN_FILE.content.decode()}).digest


def merged_digest(rule_runner: RuleRunner) -> Digest:
    return rule_runner.make_snapshot(
        {fc.path: fc.content.decode() for fc in (FORTRAN_FILE, SMALLTALK_FILE)}
    ).digest


def run_fmt(
    rule_runner: RuleRunner,
    *,
    target_specs: List[str],
    per_file_caching: bool,
    only: list[str] | None = None,
) -> str:
    result = rule_runner.run_goal_rule(
        Fmt,
        args=[
            f"--per-file-caching={per_file_caching!r}",
            f"--only={repr(only or [])}",
            *target_specs,
        ],
    )
    assert result.exit_code == 0
    assert not result.stdout
    return result.stderr


@pytest.mark.parametrize("per_file_caching", [True, False])
def test_summary(per_file_caching: bool) -> None:
    """Tests that the final summary is correct.

    This checks that we:
    * Merge multiple results for the same formatter together (when you use
        `--per-file-caching`).
    * Correctly distinguish between skipped, changed, and did not change.
    """

    rule_runner = fmt_rule_runner(
        target_types=[FortranTarget, SmalltalkTarget],
        fmt_request_types=[FortranFmtRequest, SmalltalkNoopRequest, SmalltalkSkipRequest],
    )

    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                fortran(name='f1')
                fortran(name='needs_formatting')
                smalltalk(name='s1')
                smalltalk(name='s2')
                """,
            ),
        },
    )

    stderr = run_fmt(
        rule_runner,
        target_specs=["//:f1", "//:needs_formatting", "//:s1", "//:s2"],
        per_file_caching=per_file_caching,
    )

    assert stderr == dedent(
        """\

        + FortranConditionallyDidChange made changes.
        ✓ SmalltalkDidNotChange made no changes.
        """
    )

    fortran_file = Path(rule_runner.build_root, FORTRAN_FILE.path)
    smalltalk_file = Path(rule_runner.build_root, SMALLTALK_FILE.path)
    assert fortran_file.is_file()
    assert fortran_file.read_text() == FORTRAN_FILE.content.decode()
    assert not smalltalk_file.is_file()

    stderr = run_fmt(
        rule_runner,
        target_specs=["//:f1", "//:needs_formatting", "//:s1", "//:s2"],
        per_file_caching=per_file_caching,
        only=[SmalltalkNoopRequest.name],
    )
    assert stderr.strip() == "✓ SmalltalkDidNotChange made no changes."


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
