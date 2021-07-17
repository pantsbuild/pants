# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.project_info import peek
from pants.backend.project_info.peek import Peek
from pants.core.target_types import Files
from pants.testutil.rule_runner import RuleRunner


@pytest.mark.parametrize(
    "targets, exclude_defaults, expected_output",
    [
        pytest.param(
            [],
            False,
            "[]\n",
            # dedent(
            #     """\
            #     {
            #       "targets": [],
            #       "excludeDefaults": false
            #     }
            #     """
            # ),
            id="null-case",
        )
    ],
)
def test_render_targets_as_json(targets, exclude_defaults, expected_output):
    actual_output = peek._render_json(targets, exclude_defaults)
    assert actual_output == expected_output


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(rules=peek.rules(), target_types=[Files])


def test_raw_output_single_build_file(rule_runner: RuleRunner) -> None:
    rule_runner.add_to_build_file("project", "# A comment\nfiles(sources=[])")
    result = rule_runner.run_goal_rule(Peek, args=[ "--output=raw", "project"])
    expected_output = dedent(
        """\
        -------------
        project/BUILD
        -------------
        # A comment
        files(sources=[])
        """
    )
    assert result.stdout == expected_output


def test_raw_output_two_build_files(rule_runner: RuleRunner) -> None:
    rule_runner.add_to_build_file("project1", "# A comment\nfiles(sources=[])")
    rule_runner.add_to_build_file("project2", "# Another comment\nfiles(sources=[])")
    result = rule_runner.run_goal_rule(Peek, args=[ "--output=raw", "project1", "project2"])
    expected_output = dedent(
        """\
        --------------
        project1/BUILD
        --------------
        # A comment
        files(sources=[])

        --------------
        project2/BUILD
        --------------
        # Another comment
        files(sources=[])
        """
    )
    assert result.stdout == expected_output


def test_raw_output_non_matching_build_target(rule_runner: RuleRunner) -> None:
    rule_runner.add_to_build_file("some_name", "files(sources=[])")
    result = rule_runner.run_goal_rule(Peek, args=["--output=raw", "other_name"])
    assert result.stdout == ""


def test_standard_json_output_non_matching_build_target(rule_runner: RuleRunner) -> None:
    rule_runner.add_to_build_file("some_name", "files(sources=[])")
    result = rule_runner.run_goal_rule(Peek, args=["other_name"])
    assert result.stdout == "[]\n"
