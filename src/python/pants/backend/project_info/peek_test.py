# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.project_info import peek
from pants.backend.project_info.peek import Peek, TargetData, TargetDatas
from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.core.target_types import ArchiveTarget, FilesGeneratorTarget, GenericTarget
from pants.engine.addresses import Address
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.mark.parametrize(
    "expanded_target_infos, exclude_defaults, expected_output",
    [
        pytest.param(
            [],
            False,
            "[]\n",
            id="null-case",
        ),
        pytest.param(
            [
                TargetData(
                    FilesGeneratorTarget(
                        {"sources": ["*.txt"]}, Address("example", target_name="files_target")
                    ),
                    ("foo.txt", "bar.txt"),
                    tuple(),
                )
            ],
            True,
            dedent(
                """\
                [
                  {
                    "address": "example:files_target",
                    "target_type": "files",
                    "dependencies": [],
                    "sources": [
                      "foo.txt",
                      "bar.txt"
                    ],
                    "sources_raw": [
                      "*.txt"
                    ]
                  }
                ]
                """
            ),
            id="single-files-target/exclude-defaults",
        ),
        pytest.param(
            [
                TargetData(
                    FilesGeneratorTarget(
                        {"sources": []}, Address("example", target_name="files_target")
                    ),
                    tuple(),
                    tuple(),
                )
            ],
            False,
            dedent(
                """\
                [
                  {
                    "address": "example:files_target",
                    "target_type": "files",
                    "dependencies": [],
                    "dependencies_raw": null,
                    "description": null,
                    "sources": [],
                    "sources_raw": [],
                    "tags": null
                  }
                ]
                """
            ),
            id="single-files-target/include-defaults",
        ),
        pytest.param(
            [
                TargetData(
                    FilesGeneratorTarget(
                        {"sources": ["*.txt"], "tags": ["zippable"]},
                        Address("example", target_name="files_target"),
                    ),
                    tuple(),
                    tuple(),
                ),
                TargetData(
                    ArchiveTarget(
                        {
                            "output_path": "my-archive.zip",
                            "format": "zip",
                            "files": ["example:files_target"],
                        },
                        Address("example", target_name="archive_target"),
                    ),
                    None,
                    ("foo/bar:baz", "qux:quux"),
                ),
            ],
            True,
            dedent(
                """\
                [
                  {
                    "address": "example:files_target",
                    "target_type": "files",
                    "dependencies": [],
                    "sources": [],
                    "sources_raw": [
                      "*.txt"
                    ],
                    "tags": [
                      "zippable"
                    ]
                  },
                  {
                    "address": "example:archive_target",
                    "target_type": "archive",
                    "dependencies": [
                      "foo/bar:baz",
                      "qux:quux"
                    ],
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
def test_render_targets_as_json(expanded_target_infos, exclude_defaults, expected_output):
    actual_output = peek._render_json(expanded_target_infos, exclude_defaults)
    assert actual_output == expected_output


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *peek.rules(),
            QueryRule(TargetDatas, [AddressSpecs]),
        ],
        target_types=[FilesGeneratorTarget, GenericTarget],
    )


def test_non_matching_build_target(rule_runner: RuleRunner) -> None:
    rule_runner.add_to_build_file("some_name", "files(sources=[])")
    result = rule_runner.run_goal_rule(Peek, args=["other_name"])
    assert result.stdout == "[]\n"


def test_get_target_data(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": dedent(
                """\
            target(name="bar", dependencies=[":baz"])

            files(name="baz", sources=["*.txt"])
            """
            ),
            "foo/a.txt": "",
            "foo/b.txt": "",
        }
    )
    tds = rule_runner.request(TargetDatas, [AddressSpecs([DescendantAddresses("foo")])])
    assert tds == TargetDatas(
        [
            TargetData(
                GenericTarget({"dependencies": [":baz"]}, Address("foo", target_name="bar")),
                None,
                ("foo:baz",),
            ),
            TargetData(
                FilesGeneratorTarget({"sources": ["*.txt"]}, Address("foo", target_name="baz")),
                ("foo/a.txt", "foo/b.txt"),
                tuple(),
            ),
        ]
    )


# TODO: Delete everything below this in 2.9.0.dev0.


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
