# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Iterable, List

from pants.core.goals.fix import Fix
from pants.core.goals.fix import rules as fix_rules
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest, _FmtBuildFilesRequest
from pants.core.goals.fmt import rules as fmt_rules
from pants.core.util_rules import source_files
from pants.engine.fs import (
    EMPTY_SNAPSHOT,
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    Snapshot,
)
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import FieldSet, SingleSourceField, Target
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner

SMALLTALK_FILE = FileContent("formatted.st", b"y := self size + super size.')\n")


class SmalltalkSource(SingleSourceField):
    pass


class SmalltalkTarget(Target):
    alias = "smalltalk"
    core_fields = (SmalltalkSource,)


@dataclass(frozen=True)
class SmalltalkFieldSet(FieldSet):
    required_fields = (SmalltalkSource,)

    source: SmalltalkSource


class SmalltalkNoopRequest(FmtTargetsRequest):
    goal_name = "fix"
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


class SmalltalkSkipRequest(FmtTargetsRequest):
    goal_name = "fix"
    field_set_type = SmalltalkFieldSet
    name = "SmalltalkSkipped"


@rule
async def smalltalk_skip(request: SmalltalkSkipRequest) -> FmtResult:
    assert request.snapshot != EMPTY_SNAPSHOT
    return FmtResult.skip(formatter_name=request.name)


class BrickyBuildFileFormatter(_FmtBuildFilesRequest):
    """Ensures all non-comment lines only consist of the word 'brick'."""

    goal_name = "fix"
    name = "BrickyBobby"


@rule
async def fix_with_bricky(request: BrickyBuildFileFormatter) -> FmtResult:
    def brickify(contents: bytes) -> bytes:
        content_str = contents.decode("ascii")
        new_lines = []
        for line in content_str.splitlines(keepends=True):
            if not line.startswith("#"):
                line = re.sub(r"[a-zA-Z_]+", "brick", line)
            new_lines.append(line)
        return "".join(new_lines).encode()

    digest_contents = await Get(DigestContents, Digest, request.snapshot.digest)
    new_contents = [
        dataclasses.replace(file_content, content=brickify(file_content.content))
        for file_content in digest_contents
    ]
    output_snapshot = await Get(Snapshot, CreateDigest(new_contents))

    return FmtResult(
        input=request.snapshot,
        output=output_snapshot,
        stdout="",
        stderr="",
        formatter_name=request.name,
    )


def run_fix(
    rule_runner: RuleRunner,
    *,
    target_specs: List[str],
    only: list[str] | None = None,
    extra_args: Iterable[str] = (),
) -> str:
    result = rule_runner.run_goal_rule(
        Fix,
        args=[f"--only={repr(only or [])}", *target_specs, *extra_args],
    )
    assert result.exit_code == 0
    assert not result.stdout
    return result.stderr


def write_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                smalltalk(name='s1', source="st1.st")
                smalltalk(name='s2', source="formatted.st")
                """,
            ),
            "st1.st": "y := self size + super size.')",
            "formatted.st": "y := self size + super size.')\n",
        },
    )


def test_smoke() -> None:
    """Just smoke test `fix`, as it really is just a shim around `fmt`."""
    rule_runner = RuleRunner(
        rules=[
            *collect_rules(),
            *source_files.rules(),
            *fmt_rules(),
            *fix_rules(),
            UnionRule(FmtTargetsRequest, SmalltalkSkipRequest),
            UnionRule(FmtTargetsRequest, SmalltalkNoopRequest),
            UnionRule(_FmtBuildFilesRequest, BrickyBuildFileFormatter),
        ],
        target_types=[SmalltalkTarget],
    )

    write_files(rule_runner)

    stderr = run_fix(rule_runner, target_specs=["::"])

    assert stderr == dedent(
        """\

        + BrickyBobby made changes.
        ✓ SmalltalkDidNotChange made no changes.
        """
    )

    smalltalk_file = Path(rule_runner.build_root, SMALLTALK_FILE.path)
    build_file = Path(rule_runner.build_root, "BUILD")
    assert smalltalk_file.is_file()
    assert smalltalk_file.read_text() == SMALLTALK_FILE.content.decode()
    assert build_file.is_file()
    assert build_file.read_text() == dedent(
        """\
        brick(brick='brick1', brick="brick1.brick")
        brick(brick='brick2', brick="brick.brick")
        """
    )

    write_files(rule_runner)
    stderr = run_fix(
        rule_runner,
        target_specs=["::"],
        only=[SmalltalkNoopRequest.name],
    )
    assert stderr.strip() == "✓ SmalltalkDidNotChange made no changes."
