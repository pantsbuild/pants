# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.project_info import peek
from pants.backend.project_info.peek import Peek
from pants.core.target_types import ArchiveTarget, Files
from pants.engine.addresses import Address
from pants.testutil.rule_runner import RuleRunner


@pytest.mark.parametrize(
    "targets, exclude_defaults, expected_output",
    [
        pytest.param(
            [],
            False,
            "[]\n",
            id="null-case",
        ),
        pytest.param(
            [Files({"sources": []}, Address("example", target_name="files_target"))],
            True,
            dedent(
                """\
                [
                  {
                    "address": "example:files_target",
                    "target_type": "files",
                    "sources": []
                  }
                ]
                """
            ),
            id="single-files-target/exclude-defaults",
        ),
        pytest.param(
            [Files({"sources": []}, Address("example", target_name="files_target"))],
            False,
            dedent(
                """\
                [
                  {
                    "address": "example:files_target",
                    "target_type": "files",
                    "dependencies": null,
                    "description": null,
                    "sources": [],
                    "tags": null
                  }
                ]
                """
            ),
            id="single-files-target/include-defaults",
        ),
        pytest.param(
            [
                Files(
                    {"sources": ["*.txt"], "tags": ["zippable"]},
                    Address("example", target_name="files_target"),
                ),
                ArchiveTarget(
                    {
                        "output_path": "my-archive.zip",
                        "format": "zip",
                        "files": ["example:files_target"],
                    },
                    Address("example", target_name="archive_target"),
                ),
            ],
            True,
            dedent(
                """\
                [
                  {
                    "address": "example:files_target",
                    "target_type": "files",
                    "sources": [
                      "*.txt"
                    ],
                    "tags": [
                      "zippable"
                    ]
                  },
                  {
                    "address": "example:archive_target",
                    "target_type": "archive",
                    "files": [
                      "example:files_target"
                    ],
                    "format": "zip",
                    "output_path": "my-archive.zip"
                  }
                ]
                """
            ),
            id="single-files-target/exclude-defaults",
        ),
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
    result = rule_runner.run_goal_rule(Peek, args=["--output=raw", "project"])
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
    result = rule_runner.run_goal_rule(Peek, args=["--output=raw", "project1", "project2"])
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
