# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import List, Type

from pants.core.goals.fmt import Fmt, FmtRequest, FmtResult
from pants.core.goals.fmt import rules as fmt_rules
from pants.core.util_rules import source_files
from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Digest, FileContent
from pants.engine.internals.native_engine import EMPTY_SNAPSHOT, Snapshot
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import FieldSet, SingleSourceField, Target
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.logging import LogLevel

FORTRAN_FILE = FileContent("formatted.f98", b"READ INPUT TAPE 5\n")
SMALLTALK_FILE = FileContent("formatted.st", b"y := self size + super size.')\n")


class FortranSource(SingleSourceField):
    pass


class FortranTarget(Target):
    alias = "fortran"
    core_fields = (FortranSource,)


@dataclass(frozen=True)
class FortranFieldSet(FieldSet):
    required_fields = (FortranSource,)

    sources: FortranSource


class FortranFmtRequest(FmtRequest):
    field_set_type = FortranFieldSet
    name = "FortranConditionallyDidChange"


@rule
async def fortran_fmt(request: FortranFmtRequest) -> FmtResult:
    if not any(fs.address.target_name == "needs_formatting" for fs in request.field_sets):
        return FmtResult.skip(formatter_name=request.name)
    output = await Get(Snapshot, CreateDigest([FORTRAN_FILE]))
    return FmtResult(
        input=request.snapshot, output=output, stdout="", stderr="", formatter_name=request.name
    )


class SmalltalkSource(SingleSourceField):
    pass


class SmalltalkTarget(Target):
    alias = "smalltalk"
    core_fields = (SmalltalkSource,)


@dataclass(frozen=True)
class SmalltalkFieldSet(FieldSet):
    required_fields = (SmalltalkSource,)

    source: SmalltalkSource


class SmalltalkNoopRequest(FmtRequest):
    field_set_type = SmalltalkFieldSet
    name = "SmalltalkDidNotChange"


@rule
async def smalltalk_noop(request: SmalltalkNoopRequest) -> FmtResult:
    assert request.snapshot != EMPTY_SNAPSHOT
    return FmtResult(
        input=request.snapshot,
        output=request.snapshot,
        stdout="",
        stderr="",
        formatter_name=request.name,
    )


class SmalltalkSkipRequest(FmtRequest):
    field_set_type = SmalltalkFieldSet
    name = "SmalltalkSkipped"


@rule
def smalltalk_skip(request: SmalltalkSkipRequest) -> FmtResult:
    assert request.snapshot != EMPTY_SNAPSHOT
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


def run_fmt(
    rule_runner: RuleRunner, *, target_specs: List[str], only: list[str] | None = None
) -> str:
    result = rule_runner.run_goal_rule(
        Fmt,
        args=[f"--only={repr(only or [])}", *target_specs],
    )
    assert result.exit_code == 0
    assert not result.stdout
    return result.stderr


def test_summary() -> None:
    rule_runner = fmt_rule_runner(
        target_types=[FortranTarget, SmalltalkTarget],
        # NB: Keep SmalltalkSkipRequest before SmalltalkNoopRequest so it runs first. This helps test
        # a bug where a formatter run after a skipped formatter was receiving an empty snapshot.
        # See https://github.com/pantsbuild/pants/issues/15406
        fmt_request_types=[FortranFmtRequest, SmalltalkSkipRequest, SmalltalkNoopRequest],
    )

    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                fortran(name='f1', source="ft1.f98")
                fortran(name='needs_formatting', source="formatted.f98")
                smalltalk(name='s1', source="st1.st")
                smalltalk(name='s2', source="formatted.st")
                """,
            ),
            "ft1.f98": "READ INPUT TAPE 5\n",
            "formatted.f98": "READ INPUT TAPE 5",
            "st1.st": "y := self size + super size.')",
            "formatted.st": "y := self size + super size.')\n",
        },
    )

    stderr = run_fmt(rule_runner, target_specs=["//:f1", "//:needs_formatting", "//:s1", "//:s2"])

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
    assert smalltalk_file.is_file()
    assert smalltalk_file.read_text() == SMALLTALK_FILE.content.decode()

    stderr = run_fmt(
        rule_runner,
        target_specs=["//:f1", "//:needs_formatting", "//:s1", "//:s2"],
        only=[SmalltalkNoopRequest.name],
    )
    assert stderr.strip() == "✓ SmalltalkDidNotChange made no changes."


def test_streaming_output_skip() -> None:
    result = FmtResult.skip(formatter_name="formatter")
    assert result.level() == LogLevel.DEBUG
    assert result.message() == "formatter skipped."


def test_streaming_output_changed(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    changed_digest = Digest(EMPTY_DIGEST.fingerprint, 2)
    changed_snapshot = Snapshot._unsafe_create(changed_digest, [], [])
    result = FmtResult(
        input=EMPTY_SNAPSHOT,
        output=changed_snapshot,
        stdout="stdout",
        stderr="stderr",
        formatter_name="formatter",
    )
    assert result.level() == LogLevel.WARN
    assert result.message() == "formatter made changes."
    assert ["Output from formatter\nstdout\nstderr"] == [
        rec.message for rec in caplog.records if rec.levelno == logging.DEBUG
    ]


def test_streaming_output_not_changed(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    result = FmtResult(
        input=EMPTY_SNAPSHOT,
        output=EMPTY_SNAPSHOT,
        stdout="stdout",
        stderr="stderr",
        formatter_name="formatter",
    )
    assert result.level() == LogLevel.INFO
    assert result.message() == "formatter made no changes."
    assert ["Output from formatter\nstdout\nstderr"] == [
        rec.message for rec in caplog.records if rec.levelno == logging.DEBUG
    ]
