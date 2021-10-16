# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from pants.core.goals.update_build_files import (
    RenameDeprecatedTargetsRequest,
    RenamedTargetTypes,
    RewrittenBuildFile,
    RewrittenBuildFileRequest,
    UpdateBuildFilesGoal,
    maybe_rename_deprecated_targets,
    update_build_files,
)
from pants.engine.rules import rule
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner

# ------------------------------------------------------------------------------------------
# Generic goal
# ------------------------------------------------------------------------------------------


class MockRewriteAddLine(RewrittenBuildFileRequest):
    pass


class MockRewriteReverseLines(RewrittenBuildFileRequest):
    pass


@rule
def add_line(request: MockRewriteAddLine) -> RewrittenBuildFile:
    return RewrittenBuildFile(
        request.path, (*request.lines, "added line"), change_descriptions=("Added a new line",)
    )


@rule
def reverse_lines(request: MockRewriteReverseLines) -> RewrittenBuildFile:
    return RewrittenBuildFile(
        request.path, tuple(reversed(request.lines)), change_descriptions=("Reversed lines",)
    )


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=(
            update_build_files,
            add_line,
            reverse_lines,
            UnionRule(RewrittenBuildFileRequest, MockRewriteAddLine),
            UnionRule(RewrittenBuildFileRequest, MockRewriteReverseLines),
        )
    )


def test_pipe_fixers_correctly(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"BUILD": "line\n", "dir/BUILD": "line 1\nline 2\n"})
    result = rule_runner.run_goal_rule(UpdateBuildFilesGoal)
    assert result.exit_code == 0
    assert result.stdout == dedent(
        """\
        Updated BUILD:
          - Added a new line
          - Reversed lines
        Updated dir/BUILD:
          - Added a new line
          - Reversed lines
        """
    )
    assert Path(rule_runner.build_root, "BUILD").read_text() == "added line\nline\n"
    assert Path(rule_runner.build_root, "dir/BUILD").read_text() == "added line\nline 2\nline 1\n"


# ------------------------------------------------------------------------------------------
# Renamed target types fixer
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lines",
    (
        # Already valid.
        ["new_name()"],
        ["new_name ( ) "],
        ["new_name(foo)"],
        ["new_name(", "", ")"],
        # Unrelated lines.
        ["", "123", "target()", "name='new_name'"],
        # Ignore indented
        ["  new_name()"],
    ),
)
def test_rename_deprecated_target_types_noops(lines: list[str]) -> None:
    result = maybe_rename_deprecated_targets(
        RenameDeprecatedTargetsRequest("BUILD", tuple(lines), colors_enabled=False),
        RenamedTargetTypes({"deprecated_name": "new_name"}),
    )
    assert not result.change_descriptions
    assert result.lines == tuple(lines)


@pytest.mark.parametrize(
    "lines,expected",
    (
        (["deprecated_name()"], ["new_name()"]),
        (["deprecated_name ( ) "], ["new_name ( ) "]),
        (["deprecated_name()  # comment"], ["new_name()  # comment"]),
        (["deprecated_name(", "", ")"], ["new_name(", "", ")"]),
    ),
)
def test_rename_deprecated_target_types_rewrite(lines: list[str], expected: list[str]) -> None:
    result = maybe_rename_deprecated_targets(
        RenameDeprecatedTargetsRequest("BUILD", tuple(lines), colors_enabled=False),
        RenamedTargetTypes({"deprecated_name": "new_name"}),
    )
    assert result.change_descriptions
    assert result.lines == tuple(expected)
