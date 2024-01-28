# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import itertools
import logging
import re
from dataclasses import dataclass
from pathlib import Path, PurePath
from textwrap import dedent
from typing import Iterable, List, Type

import pytest

from pants.build_graph.address import Address
from pants.core.goals.fix import (
    AbstractFixRequest,
    Fix,
    FixFilesRequest,
    FixResult,
    FixTargetsRequest,
)
from pants.core.goals.fix import rules as fix_rules
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest
from pants.core.util_rules import source_files
from pants.core.util_rules.partitions import PartitionerType, Partitions
from pants.engine.fs import (
    EMPTY_SNAPSHOT,
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    Snapshot,
)
from pants.engine.rules import Get, QueryRule, collect_rules, rule
from pants.engine.target import (
    FieldSet,
    MultipleSourcesField,
    SingleSourceField,
    StringField,
    Target,
)
from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem
from pants.testutil.rule_runner import RuleRunner
from pants.testutil.rule_runner import logging as log_this
from pants.util.logging import LogLevel
from pants.util.meta import classproperty

FORTRAN_FILE = FileContent("fixed.f98", b"READ INPUT TAPE 5\n")
RUFF_FILE = FileContent("fixed.py", b"print(input())\n")
SMALLTALK_FILE = FileContent("fixed.st", b"y := self size + super size.')\n")


class RuffSource(SingleSourceField):
    pass


class RuffTarget(Target):
    alias = "ruff"
    core_fields = (RuffSource,)


@dataclass(frozen=True)
class RuffFieldSet(FieldSet):
    required_fields = (RuffSource,)

    sources: RuffSource


class RuffFixRequest(FixTargetsRequest):
    field_set_type = RuffFieldSet

    @classproperty
    def tool_name(cls) -> str:
        return "ruff check --fix"

    @classproperty
    def tool_id(cls) -> str:
        return "ruff"


class RuffFmtRequest(FmtTargetsRequest):
    field_set_type = RuffFieldSet

    @classproperty
    def tool_name(cls) -> str:
        return "ruff format"

    @classproperty
    def tool_id(cls) -> str:
        return "ruff"


@rule
async def ruff_fix_partition(request: RuffFixRequest.PartitionRequest) -> Partitions:
    if not any(fs.address.target_name == "r_needs_fixing" for fs in request.field_sets):
        return Partitions()
    return Partitions.single_partition(fs.sources.file_path for fs in request.field_sets)


@rule
async def ruff_fmt_partition(request: RuffFmtRequest.PartitionRequest) -> Partitions:
    return Partitions.single_partition(fs.sources.file_path for fs in request.field_sets)


@rule
async def ruff_fix(request: RuffFixRequest.Batch) -> FixResult:
    input = request.snapshot
    output = await Get(
        Snapshot, CreateDigest([FileContent(file, RUFF_FILE.content) for file in request.files])
    )
    return FixResult(
        input=input, output=output, stdout="", stderr="", tool_name=RuffFixRequest.tool_name
    )


@rule
async def ruff_fmt(request: RuffFmtRequest.Batch) -> FmtResult:
    output = await Get(
        Snapshot, CreateDigest([FileContent(file, RUFF_FILE.content) for file in request.files])
    )
    return FmtResult(
        input=request.snapshot,
        output=output,
        stdout="",
        stderr="",
        tool_name=RuffFmtRequest.tool_name,
    )


class FortranSource(SingleSourceField):
    pass


class FortranTarget(Target):
    alias = "fortran"
    core_fields = (FortranSource,)


@dataclass(frozen=True)
class FortranFieldSet(FieldSet):
    required_fields = (FortranSource,)

    sources: FortranSource


class FortranFixRequest(FixTargetsRequest):
    field_set_type = FortranFieldSet

    @classproperty
    def tool_name(cls) -> str:
        return "Fortran Conditionally Did Change"

    @classproperty
    def tool_id(cls) -> str:
        return "fortranconditionallydidchange"


class FortranFmtRequest(FmtTargetsRequest):
    field_set_type = FortranFieldSet

    @classproperty
    def tool_name(cls) -> str:
        return "Fortran Formatter"

    @classproperty
    def tool_id(cls) -> str:
        return "fortranformatter"


@rule
async def fortran_fix_partition(request: FortranFixRequest.PartitionRequest) -> Partitions:
    if not any(fs.address.target_name == "needs_fixing" for fs in request.field_sets):
        return Partitions()
    return Partitions.single_partition(fs.sources.file_path for fs in request.field_sets)


@rule
async def fortran_fmt_partition(request: FortranFmtRequest.PartitionRequest) -> Partitions:
    return Partitions.single_partition(fs.sources.file_path for fs in request.field_sets)


@rule
async def fortran_fix(request: FortranFixRequest.Batch) -> FixResult:
    input = request.snapshot
    output = await Get(
        Snapshot, CreateDigest([FileContent(file, FORTRAN_FILE.content) for file in request.files])
    )
    return FixResult(
        input=input, output=output, stdout="", stderr="", tool_name=FortranFixRequest.tool_name
    )


@rule
async def fortran_fmt(request: FortranFmtRequest.Batch) -> FmtResult:
    output = await Get(
        Snapshot, CreateDigest([FileContent(file, FORTRAN_FILE.content) for file in request.files])
    )
    return FmtResult(
        input=request.snapshot,
        output=output,
        stdout="",
        stderr="",
        tool_name=FortranFmtRequest.tool_name,
    )


class SmalltalkSource(SingleSourceField):
    pass


# NB: This extra field is required to help us in `test_batches` below.
#   With it, each `SmalltalkTarget` we instantiate will produce a different `SmalltalkFieldSet`
#   (even with the same `source` field value), which then results in https://github.com/pantsbuild/pants/issues/17403.
#   See https://github.com/pantsbuild/pants/pull/19796.
class SmalltalkExtraField(StringField):
    alias = "extra"


class SmalltalkTarget(Target):
    alias = "smalltalk"
    core_fields = (SmalltalkSource, SmalltalkExtraField)


@dataclass(frozen=True)
class SmalltalkFieldSet(FieldSet):
    required_fields = (SmalltalkSource,)

    source: SmalltalkSource


class SmalltalkNoopRequest(FixTargetsRequest):
    field_set_type = SmalltalkFieldSet

    @classproperty
    def tool_name(cls) -> str:
        return "Smalltalk Did Not Change"

    @classproperty
    def tool_id(cls) -> str:
        return "smalltalkdidnotchange"


@rule
async def smalltalk_noop_partition(request: SmalltalkNoopRequest.PartitionRequest) -> Partitions:
    return Partitions.single_partition(fs.source.file_path for fs in request.field_sets)


@rule
async def smalltalk_noop(request: SmalltalkNoopRequest.Batch) -> FixResult:
    assert request.snapshot != EMPTY_SNAPSHOT
    return FixResult(
        input=request.snapshot,
        output=request.snapshot,
        stdout="",
        stderr="",
        tool_name=SmalltalkNoopRequest.tool_name,
    )


class SmalltalkSkipRequest(FixTargetsRequest):
    field_set_type = SmalltalkFieldSet

    @classproperty
    def tool_name(cls) -> str:
        return "Smalltalk Skipped"

    @classproperty
    def tool_id(cls) -> str:
        return "smalltalkskipped"


@rule
async def smalltalk_skip_partition(request: SmalltalkSkipRequest.PartitionRequest) -> Partitions:
    return Partitions()


@rule
async def smalltalk_skip(request: SmalltalkSkipRequest.Batch) -> FixResult:
    assert False


class BrickyBuildFileFixer(FixFilesRequest):
    """Ensures all non-comment lines only consist of the word 'brick'."""

    @classproperty
    def tool_name(cls) -> str:
        return "Bricky Bobby"

    @classproperty
    def tool_id(cls) -> str:
        return "brickybobby"


@rule
async def bricky_partition(request: BrickyBuildFileFixer.PartitionRequest) -> Partitions:
    return Partitions.single_partition(
        file for file in request.files if PurePath(file).name == "BUILD"
    )


@rule
async def fix_with_bricky(request: BrickyBuildFileFixer.Batch) -> FixResult:
    def brickify(contents: bytes) -> bytes:
        content_str = contents.decode("ascii")
        new_lines = []
        for line in content_str.splitlines(keepends=True):
            if not line.startswith("#"):
                line = re.sub(r"[a-zA-Z_]+", "brick", line)
            new_lines.append(line)
        return "".join(new_lines).encode()

    snapshot = request.snapshot
    digest_contents = await Get(DigestContents, Digest, snapshot.digest)
    new_contents = [
        dataclasses.replace(file_content, content=brickify(file_content.content))
        for file_content in digest_contents
    ]
    output_snapshot = await Get(Snapshot, CreateDigest(new_contents))

    return FixResult(
        input=snapshot,
        output=output_snapshot,
        stdout="",
        stderr="",
        tool_name=BrickyBuildFileFixer.tool_name,
    )


def fix_rule_runner(
    target_types: List[Type[Target]],
    request_types: List[Type[AbstractFixRequest]] = [],
) -> RuleRunner:
    return RuleRunner(
        rules=[
            *collect_rules(),
            *source_files.rules(),
            *fix_rules(),
            *itertools.chain.from_iterable(request_type.rules() for request_type in request_types),
        ],
        target_types=target_types,
    )


@log_this(level=LogLevel.INFO)
def run_fix(
    rule_runner: RuleRunner,
    *,
    target_specs: List[str],
    fmt_only: list[str] | None = None,
    fix_only: list[str] | None = None,
    extra_args: Iterable[str] = (),
) -> str:
    result = rule_runner.run_goal_rule(
        Fix,
        args=[
            f"--fmt-only={repr(fmt_only or [])}",
            f"--fix-only={repr(fix_only or [])}",
            *target_specs,
            *extra_args,
        ],
    )
    assert result.exit_code == 0
    assert not result.stdout
    return result.stderr


def write_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                ruff(name='r1', source="r1.py")
                ruff(name='r_needs_fixing', source="fixed.py")
                fortran(name='f1', source="ft1.f98")
                fortran(name='needs_fixing', source="fixed.f98")
                smalltalk(name='s1', source="st1.st")
                smalltalk(name='s2', source="fixed.st")
                """,
            ),
            "r1.py": "print(input())",
            "fixed.py": "print(input())\n",
            "ft1.f98": "READ INPUT TAPE 5\n",
            "fixed.f98": "READ INPUT TAPE 5",
            "st1.st": "y := self size + super size.')",
            "fixed.st": "y := self size + super size.')\n",
        },
    )


def test_batches(capfd) -> None:
    rule_runner = fix_rule_runner(
        target_types=[SmalltalkTarget],
        request_types=[SmalltalkNoopRequest],
    )

    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                smalltalk(name='s1-1', source="duplicate1.st")
                smalltalk(name='s1-2', source="duplicate1.st")
                smalltalk(name='s2-1', source="duplicate1.st")
                smalltalk(name='s2-2', source="duplicate2.st")
                """,
            ),
            "duplicate1.st": "",
            "duplicate2.st": "",
        },
    )
    run_fix(rule_runner, target_specs=["::"])
    assert capfd.readouterr().err.count("Smalltalk Did Not Change made no changes.") == 1


def test_summary() -> None:
    rule_runner = fix_rule_runner(
        target_types=[FortranTarget, SmalltalkTarget, RuffTarget],
        request_types=[
            FortranFixRequest,
            FortranFmtRequest,
            SmalltalkSkipRequest,
            SmalltalkNoopRequest,
            BrickyBuildFileFixer,
        ],
    )

    write_files(rule_runner)

    stderr = run_fix(rule_runner, target_specs=["::"])

    assert stderr == dedent(
        """\

        + Bricky Bobby made changes.
        + Fortran Conditionally Did Change made changes.
        ✓ Fortran Formatter made no changes.
        ✓ Smalltalk Did Not Change made no changes.
        """
    )

    fortran_file = Path(rule_runner.build_root, FORTRAN_FILE.path)
    smalltalk_file = Path(rule_runner.build_root, SMALLTALK_FILE.path)
    build_file = Path(rule_runner.build_root, "BUILD")
    assert fortran_file.is_file()
    assert fortran_file.read_text() == FORTRAN_FILE.content.decode()
    assert smalltalk_file.is_file()
    assert smalltalk_file.read_text() == SMALLTALK_FILE.content.decode()
    assert build_file.is_file()
    assert build_file.read_text() == dedent(
        """\
        brick(brick='brick1', brick="brick1.brick")
        brick(brick='brick', brick="brick.brick")
        brick(brick='brick1', brick="brick1.brick98")
        brick(brick='brick', brick="brick.brick98")
        brick(brick='brick1', brick="brick1.brick")
        brick(brick='brick2', brick="brick.brick")
        """
    )


def test_skip_formatters() -> None:
    rule_runner = fix_rule_runner(
        target_types=[FortranTarget, SmalltalkTarget, RuffTarget],
        request_types=[FortranFmtRequest],
    )

    write_files(rule_runner)

    stderr = run_fix(rule_runner, target_specs=["::"], extra_args=["--fix-skip-formatters"])

    assert not stderr


def test_fixers_first() -> None:
    rule_runner = fix_rule_runner(
        target_types=[FortranTarget, SmalltalkTarget, RuffTarget],
        # NB: Order is important here
        request_types=[FortranFmtRequest, FortranFixRequest],
    )

    write_files(rule_runner)

    stderr = run_fix(rule_runner, target_specs=["::"])

    # NB Since both rules have the same body, if the fixer runs first, it'll make changes. Then the
    # formatter will have nothing to change.
    assert stderr == dedent(
        """\

        + Fortran Conditionally Did Change made changes.
        ✓ Fortran Formatter made no changes.
        """
    )


def test_only() -> None:
    rule_runner = fix_rule_runner(
        target_types=[FortranTarget, SmalltalkTarget, RuffTarget],
        request_types=[
            FortranFixRequest,
            SmalltalkSkipRequest,
            SmalltalkNoopRequest,
            BrickyBuildFileFixer,
        ],
    )

    write_files(rule_runner)

    stderr = run_fix(
        rule_runner,
        target_specs=["::"],
        fix_only=[SmalltalkNoopRequest.tool_id],
    )
    assert stderr.strip() == "✓ Smalltalk Did Not Change made no changes."


def test_fmt_only() -> None:
    rule_runner = fix_rule_runner(
        target_types=[
            FortranTarget,
            RuffTarget,
            SmalltalkTarget,
        ],
        request_types=[
            FortranFixRequest,
            FortranFmtRequest,
            RuffFixRequest,
            RuffFmtRequest,
        ],
    )

    write_files(rule_runner)

    stderr = run_fix(
        rule_runner,
        target_specs=["::"],
        fmt_only=[FortranFmtRequest.tool_id],
    )
    expected = dedent(
        """
        + Fortran Conditionally Did Change made changes.
        ✓ Fortran Formatter made no changes.
        + ruff check --fix made changes.
        """
    ).strip()
    assert stderr.strip() == expected


def test_fix_only() -> None:
    rule_runner = fix_rule_runner(
        target_types=[
            FortranTarget,
            RuffTarget,
            SmalltalkTarget,
        ],
        request_types=[
            BrickyBuildFileFixer,
            FortranFixRequest,
            FortranFmtRequest,
            RuffFixRequest,
            RuffFmtRequest,
            SmalltalkNoopRequest,
            SmalltalkSkipRequest,
        ],
    )

    write_files(rule_runner)

    stderr = run_fix(
        rule_runner,
        target_specs=["::"],
        fix_only=[RuffFixRequest.tool_id],
    )
    expected = dedent(
        """
        + ruff check --fix made changes.
        ✓ ruff format made no changes.
        """
    ).strip()
    assert stderr.strip() == expected


def test_no_targets() -> None:
    rule_runner = fix_rule_runner(
        target_types=[FortranTarget, SmalltalkTarget, RuffTarget],
        request_types=[
            FortranFixRequest,
            SmalltalkSkipRequest,
            SmalltalkNoopRequest,
            BrickyBuildFileFixer,
        ],
    )

    write_files(rule_runner)

    stderr = run_fix(
        rule_runner,
        target_specs=[],
    )
    assert not stderr.strip()


def test_message_lists_added_files() -> None:
    input_snapshot = Snapshot.create_for_testing(["f.ext", "dir/f.ext"], ["dir"])
    output_snapshot = Snapshot.create_for_testing(["f.ext", "added.ext", "dir/f.ext"], ["dir"])
    result = FixResult(
        input=input_snapshot,
        output=output_snapshot,
        stdout="stdout",
        stderr="stderr",
        tool_name="fixer",
    )
    assert result.message() == "fixer made changes.\n  added.ext"


def test_message_lists_removed_files() -> None:
    input_snapshot = Snapshot.create_for_testing(["f.ext", "removed.ext", "dir/f.ext"], ["dir"])
    output_snapshot = Snapshot.create_for_testing(["f.ext", "dir/f.ext"], ["dir"])
    result = FixResult(
        input=input_snapshot,
        output=output_snapshot,
        stdout="stdout",
        stderr="stderr",
        tool_name="fixer",
    )
    assert result.message() == "fixer made changes.\n  removed.ext"


def test_message_lists_files() -> None:
    input_snapshot = Snapshot.create_for_testing(["f.ext", "removed.ext", "dir/f.ext"], ["dir"])
    output_snapshot = Snapshot.create_for_testing(["f.ext", "added.ext", "dir/f.ext"], ["dir"])
    result = FixResult(
        input=input_snapshot,
        output=output_snapshot,
        stdout="stdout",
        stderr="stderr",
        tool_name="fixer",
    )
    assert result.message() == "fixer made changes.\n  added.ext\n  removed.ext"


@dataclass(frozen=True)
class KitchenSingleUtensilFieldSet(FieldSet):
    required_fields = (FortranSource,)

    utensil: SingleSourceField


@dataclass(frozen=True)
class KitchenMultipleUtensilsFieldSet(FieldSet):
    required_fields = (FortranSource,)

    utensils: MultipleSourcesField


@pytest.mark.parametrize(
    "kitchen_field_set_type, field_sets",
    [
        (
            KitchenSingleUtensilFieldSet,
            (
                KitchenSingleUtensilFieldSet(
                    Address("//:bowl"), SingleSourceField("bowl.utensil", Address(""))
                ),
                KitchenSingleUtensilFieldSet(
                    Address("//:knife"), SingleSourceField("knife.utensil", Address(""))
                ),
            ),
        ),
        (
            KitchenMultipleUtensilsFieldSet,
            (
                KitchenMultipleUtensilsFieldSet(
                    Address("//:utensils"),
                    MultipleSourcesField(["*.utensil"], Address("")),
                ),
            ),
        ),
    ],
)
def test_default_single_partition_partitioner(kitchen_field_set_type, field_sets) -> None:
    class KitchenSubsystem(Subsystem):
        options_scope = "kitchen"
        help = "a cookbook might help"
        name = "The Kitchen"
        skip = SkipOption("lint")

    class FixKitchenRequest(FixTargetsRequest):
        field_set_type = kitchen_field_set_type
        tool_subsystem = KitchenSubsystem
        partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION

    rules = [
        *FixKitchenRequest._get_rules(),
        QueryRule(Partitions, [FixKitchenRequest.PartitionRequest]),
    ]
    rule_runner = RuleRunner(rules=rules)
    rule_runner.write_files({"BUILD": "", "knife.utensil": "", "bowl.utensil": ""})
    partitions = rule_runner.request(Partitions, [FixKitchenRequest.PartitionRequest(field_sets)])
    assert len(partitions) == 1
    assert partitions[0].elements == ("bowl.utensil", "knife.utensil")

    rule_runner.set_options(["--kitchen-skip"])
    partitions = rule_runner.request(Partitions, [FixKitchenRequest.PartitionRequest(field_sets)])
    assert partitions == Partitions([])


def test_streaming_output_changed(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    changed_snapshot = Snapshot.create_for_testing(["other_file.txt"], [])
    result = FixResult(
        input=EMPTY_SNAPSHOT,
        output=changed_snapshot,
        stdout="stdout",
        stderr="stderr",
        tool_name="fixer",
    )
    assert result.level() == LogLevel.WARN
    assert result.message() == "fixer made changes.\n  other_file.txt"
    assert ["Output from fixer\nstdout\nstderr"] == [
        rec.message for rec in caplog.records if rec.levelno == logging.DEBUG
    ]


def test_streaming_output_not_changed(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    result = FixResult(
        input=EMPTY_SNAPSHOT,
        output=EMPTY_SNAPSHOT,
        stdout="stdout",
        stderr="stderr",
        tool_name="fixer",
    )
    assert result.level() == LogLevel.INFO
    assert result.message() == "fixer made no changes."
    assert ["Output from fixer\nstdout\nstderr"] == [
        rec.message for rec in caplog.records if rec.levelno == logging.DEBUG
    ]
