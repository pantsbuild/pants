# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from textwrap import dedent
from typing import List, Optional, Sequence, cast

import pytest

from pants.backend.project_info.filter_targets import (
    FilterSubsystem,
    TargetGranularity,
    filter_targets,
)
from pants.engine.addresses import Address
from pants.engine.target import (
    RegisteredTargetTypes,
    Tags,
    Target,
    Targets,
    UnrecognizedTargetTypeException,
)
from pants.testutil.option_util import create_goal_subsystem
from pants.testutil.rule_runner import MockConsole, run_rule_with_mocks


class MockTarget(Target):
    alias = "tgt"
    core_fields = (Tags,)


def run_goal(
    targets: Sequence[Target],
    *,
    target_type: Optional[List[str]] = None,
    address_regex: Optional[List[str]] = None,
    tag_regex: Optional[List[str]] = None,
    granularity: Optional[TargetGranularity] = None,
) -> str:
    console = MockConsole(use_colors=False)
    run_rule_with_mocks(
        filter_targets,
        rule_args=[
            Targets(targets),
            create_goal_subsystem(
                FilterSubsystem,
                sep="\\n",
                output_file=None,
                target_type=target_type or [],
                address_regex=address_regex or [],
                tag_regex=tag_regex or [],
                granularity=granularity or TargetGranularity.all_targets,
                # Deprecated.
                type=[],
                target=[],
                regex=[],
                ancestor=[],
            ),
            console,
            RegisteredTargetTypes.create({type(tgt) for tgt in targets}),
        ],
    )
    assert not console.stderr.getvalue()
    return cast(str, console.stdout.getvalue())


def test_no_filters_provided() -> None:
    # `filter` behaves like `list` when there are no specified filters.
    targets = [MockTarget({}, address=Address("", target_name=name)) for name in ("t3", "t2", "t1")]
    assert run_goal(targets) == dedent(
        """\
        //:t1
        //:t2
        //:t3
        """
    )


def test_filter_by_target_type() -> None:
    class Fortran(Target):
        alias = "fortran"
        core_fields = ()

    class Smalltalk(Target):
        alias = "smalltalk"
        core_fields = ()

    fortran_targets = [Fortran({}, address=Address("", target_name=name)) for name in ("f1", "f2")]
    smalltalk_targets = [
        Smalltalk({}, address=Address("", target_name=name)) for name in ("s1", "s2")
    ]
    targets = [*fortran_targets, *smalltalk_targets]

    assert run_goal(targets, target_type=["fortran"]).strip() == "//:f1\n//:f2"
    assert run_goal(targets, target_type=["+smalltalk"]).strip() == "//:s1\n//:s2"
    assert run_goal(targets, target_type=["-smalltalk"]).strip() == "//:f1\n//:f2"
    # The comma is inside the string, so these are ORed.
    assert run_goal(targets, target_type=["fortran,smalltalk"]) == dedent(
        """\
        //:f1
        //:f2
        //:s1
        //:s2
        """
    )

    # A target can only have one type, so this output should be empty.
    assert run_goal(targets, target_type=["fortran", "smalltalk"]) == ""

    with pytest.raises(UnrecognizedTargetTypeException):
        run_goal(targets, target_type=["invalid"])


def test_filter_by_address_regex() -> None:
    targets = [
        MockTarget({}, address=addr)
        for addr in (
            Address("dir1", target_name="lib"),
            Address("dir2", target_name="lib"),
            Address("common", target_name="tests"),
        )
    ]
    assert run_goal(targets, address_regex=[r"^dir"]).strip() == "dir1:lib\ndir2:lib"
    assert run_goal(targets, address_regex=[r"+dir1:lib$"]).strip() == "dir1:lib"
    assert run_goal(targets, address_regex=["-dir"]).strip() == "common:tests"
    # The comma ORs the regex.
    assert run_goal(targets, address_regex=["dir1,common"]).strip() == "common:tests\ndir1:lib"
    # This ANDs the regex.
    assert run_goal(targets, address_regex=[r"^dir", "2:lib$"]).strip() == "dir2:lib"

    # Invalid regex.
    with pytest.raises(re.error):
        run_goal(targets, tag_regex=["("])


def test_filter_by_tag_regex() -> None:
    targets = [
        MockTarget({"tags": ["tag1"]}, address=Address("", target_name="t1")),
        MockTarget({"tags": ["tag2"]}, address=Address("", target_name="t2")),
        MockTarget({"tags": ["tag1", "tag2"]}, address=Address("", target_name="both")),
        MockTarget({}, address=Address("", target_name="no_tags")),
    ]
    assert run_goal(targets, tag_regex=[r"t.?g2$"]).strip() == "//:both\n//:t2"
    assert run_goal(targets, tag_regex=["+tag1"]).strip() == "//:both\n//:t1"
    assert run_goal(targets, tag_regex=["-tag"]).strip() == "//:no_tags"
    # The comma ORs the regex.
    assert run_goal(targets, tag_regex=[r"t.?g2$,tag1"]).strip() == "//:both\n//:t1\n//:t2"
    # This ANDs the regex.
    assert run_goal(targets, tag_regex=[r"t.?g2$", "tag1"]).strip() == "//:both"

    # Invalid regex.
    with pytest.raises(re.error):
        run_goal(targets, tag_regex=["("])


def test_filter_by_granularity() -> None:
    targets = [
        MockTarget({}, address=Address("p1")),
        MockTarget({}, address=Address("p1", relative_file_path="file.txt")),
    ]
    assert run_goal(targets, granularity=TargetGranularity.all_targets).strip() == "p1\np1/file.txt"
    assert run_goal(targets, granularity=TargetGranularity.base_targets).strip() == "p1"
    assert run_goal(targets, granularity=TargetGranularity.file_targets).strip() == "p1/file.txt"
