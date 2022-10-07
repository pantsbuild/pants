# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
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
from pants.core.goals.fmt import (
    Fmt,
    FmtFilesRequest,
    FmtRequest,
    FmtResult,
    FmtTargetsRequest,
    Partitions,
)
from pants.core.goals.fmt import rules as fmt_rules
from pants.core.goals.lint import PartitionerType
from pants.core.util_rules import source_files
from pants.engine.fs import (
    EMPTY_DIGEST,
    EMPTY_SNAPSHOT,
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    Snapshot,
)
from pants.engine.rules import Get, QueryRule, collect_rules, rule
from pants.engine.target import FieldSet, MultipleSourcesField, SingleSourceField, Target
from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem
from pants.testutil.rule_runner import RuleRunner
from pants.util.logging import LogLevel
from pants.util.meta import classproperty

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


class FortranFmtRequest(FmtTargetsRequest):
    field_set_type = FortranFieldSet

    @classproperty
    def tool_name(cls) -> str:
        return "FortranConditionallyDidChange"


@rule
async def fortran_partition(request: FortranFmtRequest.PartitionRequest) -> Partitions:
    if not any(fs.address.target_name == "needs_formatting" for fs in request.field_sets):
        return Partitions()
    return Partitions.single_partition(fs.sources.file_path for fs in request.field_sets)


@rule
async def fortran_fmt(request: FortranFmtRequest.SubPartition) -> FmtResult:
    input = request.snapshot
    output = await Get(
        Snapshot, CreateDigest([FileContent(file, FORTRAN_FILE.content) for file in request.files])
    )
    return FmtResult(
        input=input, output=output, stdout="", stderr="", formatter_name=FortranFmtRequest.tool_name
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


class SmalltalkNoopRequest(FmtTargetsRequest):
    field_set_type = SmalltalkFieldSet

    @classproperty
    def tool_name(cls) -> str:
        return "SmalltalkDidNotChange"


@rule
async def smalltalk_noop_partition(request: SmalltalkNoopRequest.PartitionRequest) -> Partitions:
    return Partitions.single_partition(fs.source.file_path for fs in request.field_sets)


@rule
async def smalltalk_noop(request: SmalltalkNoopRequest.SubPartition) -> FmtResult:
    assert request.snapshot != EMPTY_SNAPSHOT
    return FmtResult(
        input=request.snapshot,
        output=request.snapshot,
        stdout="",
        stderr="",
        formatter_name=SmalltalkNoopRequest.tool_name,
    )


class SmalltalkSkipRequest(FmtTargetsRequest):
    field_set_type = SmalltalkFieldSet

    @classproperty
    def tool_name(cls) -> str:
        return "SmalltalkSkipped"


@rule
async def smalltalk_skip_partition(request: SmalltalkSkipRequest.PartitionRequest) -> Partitions:
    return Partitions()


@rule
async def smalltalk_skip(request: SmalltalkSkipRequest.SubPartition) -> FmtResult:
    assert False


class BrickyBuildFileFormatter(FmtFilesRequest):
    """Ensures all non-comment lines only consist of the word 'brick'."""

    @classproperty
    def tool_name(cls) -> str:
        return "BrickyBobby"


@rule
async def bricky_partition(request: BrickyBuildFileFormatter.PartitionRequest) -> Partitions:
    return Partitions.single_partition(
        file for file in request.files if PurePath(file).name == "BUILD"
    )


@rule
async def fmt_with_bricky(request: BrickyBuildFileFormatter.SubPartition) -> FmtResult:
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

    return FmtResult(
        input=snapshot,
        output=output_snapshot,
        stdout="",
        stderr="",
        formatter_name=BrickyBuildFileFormatter.tool_name,
    )


def fmt_rule_runner(
    target_types: List[Type[Target]],
    request_types: List[Type[FmtRequest]] = [],
) -> RuleRunner:
    return RuleRunner(
        rules=[
            *collect_rules(),
            *source_files.rules(),
            *fmt_rules(),
            *itertools.chain.from_iterable(request_type.rules() for request_type in request_types),
        ],
        target_types=target_types,
    )


def run_fmt(
    rule_runner: RuleRunner,
    *,
    target_specs: List[str],
    only: list[str] | None = None,
    extra_args: Iterable[str] = (),
) -> str:
    result = rule_runner.run_goal_rule(
        Fmt,
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


def test_summary() -> None:
    rule_runner = fmt_rule_runner(
        target_types=[FortranTarget, SmalltalkTarget],
        request_types=[
            FortranFmtRequest,
            SmalltalkSkipRequest,
            SmalltalkNoopRequest,
            BrickyBuildFileFormatter,
        ],
    )

    write_files(rule_runner)

    stderr = run_fmt(rule_runner, target_specs=["::"])

    assert stderr == dedent(
        """\

        + BrickyBobby made changes.
        + FortranConditionallyDidChange made changes.
        ✓ SmalltalkDidNotChange made no changes.
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
        brick(brick='brick1', brick="brick1.brick98")
        brick(brick='brick', brick="brick.brick98")
        brick(brick='brick1', brick="brick1.brick")
        brick(brick='brick2', brick="brick.brick")
        """
    )


def test_build_spec_matching() -> None:
    rule_runner = fmt_rule_runner(
        target_types=[],
        request_types=[BrickyBuildFileFormatter],
    )
    original_contents = "build_file_dir"  # just choose something built-in that'll be replaced

    # Added type to workaround https://github.com/python/typing/issues/445
    build_files: dict[str | PurePath, str] = {
        "BUILD": original_contents,
        "dirA/BUILD": original_contents,
        "dirA/subdirX/BUILD": original_contents,
        "dirA/subdirY/BUILD": original_contents,
        "dirB/BUILD": original_contents,
        "dirC/BUILD": original_contents,
    }

    def assert_only_changed(*paths):
        all_paths = set(build_files.keys())
        for path in paths:
            assert Path(rule_runner.build_root, path).read_text() != original_contents
            all_paths.remove(path)
        for path in all_paths:
            assert Path(rule_runner.build_root, path).read_text() == original_contents

    rule_runner.write_files(build_files)
    run_fmt(rule_runner, target_specs=["::"])
    assert_only_changed(*build_files)

    rule_runner.write_files(build_files)
    run_fmt(rule_runner, target_specs=["dirA:"])
    assert_only_changed("dirA/BUILD")

    rule_runner.write_files(build_files)
    run_fmt(rule_runner, target_specs=["dirA::"])
    assert_only_changed("dirA/BUILD", "dirA/subdirX/BUILD", "dirA/subdirY/BUILD")

    rule_runner.write_files(build_files)
    run_fmt(rule_runner, target_specs=["dirA::", "dirB/BUILD"])
    assert_only_changed("dirA/BUILD", "dirA/subdirX/BUILD", "dirA/subdirY/BUILD", "dirB/BUILD")

    rule_runner.write_files(build_files)
    run_fmt(rule_runner, target_specs=["dirA::", "!dirA/subdirX:"])
    assert_only_changed("dirA/BUILD", "dirA/subdirY/BUILD")


def test_only() -> None:
    rule_runner = fmt_rule_runner(
        target_types=[FortranTarget, SmalltalkTarget],
        request_types=[
            FortranFmtRequest,
            SmalltalkSkipRequest,
            SmalltalkNoopRequest,
            BrickyBuildFileFormatter,
        ],
    )

    write_files(rule_runner)

    stderr = run_fmt(
        rule_runner,
        target_specs=["::"],
        only=[SmalltalkNoopRequest.tool_name],
    )
    assert stderr.strip() == "✓ SmalltalkDidNotChange made no changes."


def test_no_targets() -> None:
    rule_runner = fmt_rule_runner(
        target_types=[FortranTarget, SmalltalkTarget],
        request_types=[
            FortranFmtRequest,
            SmalltalkSkipRequest,
            SmalltalkNoopRequest,
            BrickyBuildFileFormatter,
        ],
    )

    write_files(rule_runner)

    stderr = run_fmt(
        rule_runner,
        target_specs=[],
    )
    assert not stderr.strip()


def test_message_lists_added_files() -> None:
    input_snapshot = Snapshot._unsafe_create(
        Digest("a" * 64, 1000), ["f.ext", "dir/f.ext"], ["dir"]
    )
    output_snapshot = Snapshot._unsafe_create(
        Digest("b" * 64, 1000), ["f.ext", "added.ext", "dir/f.ext"], ["dir"]
    )
    result = FmtResult(
        input=input_snapshot,
        output=output_snapshot,
        stdout="stdout",
        stderr="stderr",
        formatter_name="formatter",
    )
    assert result.message() == "formatter made changes.\n  added.ext"


def test_message_lists_removed_files() -> None:
    input_snapshot = Snapshot._unsafe_create(
        Digest("a" * 64, 1000), ["f.ext", "removed.ext", "dir/f.ext"], ["dir"]
    )
    output_snapshot = Snapshot._unsafe_create(
        Digest("b" * 64, 1000), ["f.ext", "dir/f.ext"], ["dir"]
    )
    result = FmtResult(
        input=input_snapshot,
        output=output_snapshot,
        stdout="stdout",
        stderr="stderr",
        formatter_name="formatter",
    )
    assert result.message() == "formatter made changes.\n  removed.ext"


def test_message_lists_files() -> None:
    # _unsafe_create() cannot be used to simulate changed files,
    # so just make sure added and removed work together.
    input_snapshot = Snapshot._unsafe_create(
        Digest("a" * 64, 1000), ["f.ext", "removed.ext", "dir/f.ext"], ["dir"]
    )
    output_snapshot = Snapshot._unsafe_create(
        Digest("b" * 64, 1000), ["f.ext", "added.ext", "dir/f.ext"], ["dir"]
    )
    result = FmtResult(
        input=input_snapshot,
        output=output_snapshot,
        stdout="stdout",
        stderr="stderr",
        formatter_name="formatter",
    )
    assert result.message() == "formatter made changes.\n  added.ext\n  removed.ext"


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

    class FmtKitchenRequest(FmtTargetsRequest):
        field_set_type = kitchen_field_set_type
        tool_subsystem = KitchenSubsystem
        partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION

    rules = [
        *FmtKitchenRequest._get_rules(),
        QueryRule(Partitions, [FmtKitchenRequest.PartitionRequest]),
    ]
    rule_runner = RuleRunner(rules=rules)
    print(rule_runner.write_files({"BUILD": "", "knife.utensil": "", "bowl.utensil": ""}))
    partitions = rule_runner.request(Partitions, [FmtKitchenRequest.PartitionRequest(field_sets)])
    assert partitions == Partitions(
        [
            (
                None,
                (
                    "bowl.utensil",
                    "knife.utensil",
                ),
            )
        ]
    )

    rule_runner.set_options(["--kitchen-skip"])
    partitions = rule_runner.request(Partitions, [FmtKitchenRequest.PartitionRequest(field_sets)])
    assert partitions == Partitions([])


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
