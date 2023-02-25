# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.project_info import peek
from pants.backend.project_info.peek import Peek, TargetData, TargetDatas
from pants.backend.visibility.rules import rules as visibility_rules
from pants.base.specs import RawSpecs, RecursiveGlobSpec
from pants.core.target_types import ArchiveTarget, FilesGeneratorTarget, FileTarget, GenericTarget
from pants.engine.addresses import Address
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.mark.parametrize(
    "expanded_target_infos, exclude_defaults, include_dep_rules, expected_output",
    [
        pytest.param(
            [],
            False,
            False,
            "[]\n",
            id="null-case",
        ),
        pytest.param(
            [
                TargetData(
                    FilesGeneratorTarget(
                        {
                            "sources": ["*.txt"],
                            # Regression test that we can handle a dict with `tuple[str, ...]` as
                            # key.
                            "overrides": {("foo.txt",): {"tags": ["overridden"]}},
                        },
                        Address("example", target_name="files_target"),
                    ),
                    ("foo.txt", "bar.txt"),
                    tuple(),
                )
            ],
            True,
            False,
            dedent(
                """\
                [
                  {
                    "address": "example:files_target",
                    "target_type": "files",
                    "dependencies": [],
                    "overrides": {
                      "('foo.txt',)": {
                        "tags": [
                          "overridden"
                        ]
                      }
                    },
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
                        {"sources": ["foo.txt"]}, Address("example", target_name="files_target")
                    ),
                    ("foo.txt",),
                    tuple(),
                )
            ],
            False,
            False,
            dedent(
                """\
                [
                  {
                    "address": "example:files_target",
                    "target_type": "files",
                    "dependencies": [],
                    "description": null,
                    "overrides": null,
                    "sources": [
                      "foo.txt"
                    ],
                    "sources_raw": [
                      "foo.txt"
                    ],
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
            False,
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
        pytest.param(
            [
                TargetData(
                    FilesGeneratorTarget({"sources": ["*.txt"]}, Address("foo", target_name="baz")),
                    ("foo/a.txt",),
                    ("foo/a.txt:baz",),
                    dependencies_rules=("does", "apply", "*"),
                    dependents_rules=("fall-through", "*"),
                    applicable_dep_rules=(
                        "foo/BUILD[*] -> foo/BUILD[*] : ALLOW\nfiles foo:baz -> files foo/a.txt:baz",
                    ),
                ),
            ],
            True,
            True,
            dedent(
                """\
                [
                  {
                    "address": "foo:baz",
                    "target_type": "files",
                    "_applicable_dep_rules": [
                      "foo/BUILD[*] -> foo/BUILD[*] : ALLOW\\nfiles foo:baz -> files foo/a.txt:baz"
                    ],
                    "_dependencies_rules": [
                      "does",
                      "apply",
                      "*"
                    ],
                    "_dependents_rules": [
                      "fall-through",
                      "*"
                    ],
                    "dependencies": [
                      "foo/a.txt:baz"
                    ],
                    "sources": [
                      "foo/a.txt"
                    ],
                    "sources_raw": [
                      "*.txt"
                    ]
                  }
                ]
                """
            ),
            id="include-dep-rules",
        ),
    ],
)
def test_render_targets_as_json(
    expanded_target_infos, exclude_defaults, include_dep_rules, expected_output
):
    actual_output = peek.render_json(expanded_target_infos, exclude_defaults, include_dep_rules)
    assert actual_output == expected_output


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *peek.rules(),
            *visibility_rules(),
            QueryRule(TargetDatas, [RawSpecs]),
        ],
        target_types=[FilesGeneratorTarget, GenericTarget],
    )


def test_non_matching_build_target(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"some_name/BUILD": "target()"})
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
    tds = rule_runner.request(
        TargetDatas,
        [RawSpecs(recursive_globs=(RecursiveGlobSpec("foo"),), description_of_origin="tests")],
    )
    assert list(tds) == [
        TargetData(
            GenericTarget({"dependencies": [":baz"]}, Address("foo", target_name="bar")),
            None,
            ("foo/a.txt:baz", "foo/b.txt:baz"),
        ),
        TargetData(
            FilesGeneratorTarget({"sources": ["*.txt"]}, Address("foo", target_name="baz")),
            ("foo/a.txt", "foo/b.txt"),
            ("foo/a.txt:baz", "foo/b.txt:baz"),
        ),
        TargetData(
            FileTarget(
                {"source": "a.txt"}, Address("foo", relative_file_path="a.txt", target_name="baz")
            ),
            ("foo/a.txt",),
            (),
        ),
        TargetData(
            FileTarget(
                {"source": "b.txt"}, Address("foo", relative_file_path="b.txt", target_name="baz")
            ),
            ("foo/b.txt",),
            (),
        ),
    ]


def test_get_target_data_with_dep_rules(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--peek-include-dep-rules"])
    rule_runner.write_files(
        {
            "foo/BUILD": dedent(
                """\
                files(name="baz", sources=["*.txt"])
                __dependencies_rules__(
                  ("<target>", "does", "not", "apply", "*"),
                  ("<files>", "does", "apply", "*"),
                )
                __dependents_rules__(
                  ("b.txt", "!skip", "this", "*"),
                  ("<file>", "take", "the", "first", "*"),
                  ("*", "fall-through", "*"),
                )
                """
            ),
            "foo/a.txt": "",
        }
    )
    tds = rule_runner.request(
        TargetDatas,
        [RawSpecs(recursive_globs=(RecursiveGlobSpec("foo"),), description_of_origin="tests")],
    )
    assert list(tds) == [
        TargetData(
            FilesGeneratorTarget({"sources": ["*.txt"]}, Address("foo", target_name="baz")),
            ("foo/a.txt",),
            ("foo/a.txt:baz",),
            dependencies_rules=("does", "apply", "*"),
            dependents_rules=("fall-through", "*"),
            applicable_dep_rules=(
                "foo/BUILD[*] -> foo/BUILD[*] : ALLOW\nfiles foo:baz -> files foo/a.txt:baz",
            ),
        ),
        TargetData(
            FileTarget(
                {"source": "a.txt"}, Address("foo", relative_file_path="a.txt", target_name="baz")
            ),
            ("foo/a.txt",),
            (),
            dependencies_rules=("does", "apply", "*"),
            dependents_rules=("fall-through", "*"),
            applicable_dep_rules=(),
        ),
    ]
