# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from textwrap import dedent
from typing import List, Optional, Sequence, cast

import pytest

from pants.backend.project_info.filter_targets import FilterOptions, filter_targets
from pants.engine.addresses import Address
from pants.engine.target import (
    RegisteredTargetTypes,
    Tags,
    Target,
    Targets,
    UnrecognizedTargetTypeException,
)
from pants.testutil.engine.util import MockConsole, create_goal_subsystem, run_rule


class MockTarget(Target):
    alias = "tgt"
    core_fields = (Tags,)


def run_goal(
    targets: Sequence[Target],
    *,
    target_type: Optional[List[str]] = None,
    address_regex: Optional[List[str]] = None,
    tag_regex: Optional[List[str]] = None,
) -> str:
    console = MockConsole(use_colors=False)
    run_rule(
        filter_targets,
        rule_args=[
            Targets(targets),
            create_goal_subsystem(
                FilterOptions,
                sep="\\n",
                output_file=None,
                target_type=target_type or [],
                address_regex=address_regex or [],
                tag_regex=tag_regex or [],
            ),
            console,
            RegisteredTargetTypes.create({type(tgt) for tgt in targets}),
        ],
    )
    assert not console.stderr.getvalue()
    return cast(str, console.stdout.getvalue())


def test_no_filters_provided() -> None:
    # `filter` behaves like `list` when there are no specified filters.
    targets = [MockTarget({}, address=Address.parse(addr)) for addr in (":t3", ":t2", ":t1")]
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

    fortran_targets = [Fortran({}, address=Address.parse(addr)) for addr in (":f1", ":f2")]
    smalltalk_targets = [Smalltalk({}, address=Address.parse(addr)) for addr in (":s1", ":s2")]
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
        MockTarget({}, address=Address.parse(addr))
        for addr in ("dir1:lib", "dir2:lib", "common:tests")
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
        MockTarget({"tags": ["tag1"]}, address=Address.parse(":t1")),
        MockTarget({"tags": ["tag2"]}, address=Address.parse(":t2")),
        MockTarget({"tags": ["tag1", "tag2"]}, address=Address.parse(":both")),
        MockTarget({}, address=Address.parse(":no_tags")),
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
