# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
from textwrap import dedent

import pytest

from pants.backend.project_info import peek
from pants.backend.project_info.peek import Peek, TargetData, TargetDatas
from pants.base.specs import RawSpecs, RecursiveGlobSpec
from pants.core.target_types import ArchiveTarget, FilesGeneratorTarget, FileTarget, GenericTarget
from pants.engine.addresses import Address
from pants.engine.fs import Digest, Snapshot
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


def _snapshot(fingerprint: str, files: tuple[str, ...]) -> Snapshot:
    return Snapshot._unsafe_create(Digest(fingerprint.ljust(64, "0"), 1), files, ())


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
                        {
                            "sources": ["*.txt"],
                            # Regression test that we can handle a dict with `tuple[str, ...]` as
                            # key.
                            "overrides": {("foo.txt",): {"tags": ["overridden"]}},
                        },
                        Address("example", target_name="files_target"),
                    ),
                    _snapshot(
                        "2",
                        ("foo.txt", "bar.txt"),
                    ),
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
                    "overrides": {
                      "('foo.txt',)": {
                        "tags": [
                          "overridden"
                        ]
                      }
                    },
                    "sources": [
                      "bar.txt",
                      "foo.txt"
                    ],
                    "sources_fingerprint": "2000000000000000000000000000000000000000000000000000000000000000",
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
                    _snapshot(
                        "1",
                        ("foo.txt",),
                    ),
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
                    "description": null,
                    "overrides": null,
                    "sources": [
                      "foo.txt"
                    ],
                    "sources_fingerprint": "1000000000000000000000000000000000000000000000000000000000000000",
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
                    _snapshot(
                        "0",
                        (),
                    ),
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
                    "sources_fingerprint": "0000000000000000000000000000000000000000000000000000000000000000",
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
    actual_output = peek.render_json(expanded_target_infos, exclude_defaults)
    assert actual_output == expected_output


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *peek.rules(),
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

    normalised = [
        dataclasses.replace(
            td,
            expanded_sources=None
            if td.expanded_sources is None
            else _snapshot("", td.expanded_sources.files),
        )
        for td in tds
    ]

    assert normalised == [
        TargetData(
            GenericTarget({"dependencies": [":baz"]}, Address("foo", target_name="bar")),
            None,
            ("foo/a.txt:baz", "foo/b.txt:baz"),
        ),
        TargetData(
            FilesGeneratorTarget({"sources": ["*.txt"]}, Address("foo", target_name="baz")),
            _snapshot("", ("foo/a.txt", "foo/b.txt")),
            ("foo/a.txt:baz", "foo/b.txt:baz"),
        ),
        TargetData(
            FileTarget(
                {"source": "a.txt"}, Address("foo", relative_file_path="a.txt", target_name="baz")
            ),
            _snapshot("", ("foo/a.txt",)),
            (),
        ),
        TargetData(
            FileTarget(
                {"source": "b.txt"}, Address("foo", relative_file_path="b.txt", target_name="baz")
            ),
            _snapshot("", ("foo/b.txt",)),
            (),
        ),
    ]
