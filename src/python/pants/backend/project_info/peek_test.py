# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
from textwrap import dedent
from typing import Sequence

import pytest

from pants.backend.project_info import peek
from pants.backend.project_info.peek import Peek, TargetData, TargetDatas
from pants.backend.visibility.rules import rules as visibility_rules
from pants.base.specs import RawSpecs, RecursiveGlobSpec
from pants.core.target_types import ArchiveTarget, FilesGeneratorTarget, FileTarget, GenericTarget
from pants.engine.addresses import Address
from pants.engine.fs import Snapshot
from pants.engine.internals.dep_rules import DependencyRuleAction, DependencyRuleApplication
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


def _snapshot(fingerprint: str, files: tuple[str, ...]) -> Snapshot:
    return Snapshot.create_for_testing(files, ())


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
                    _snapshot(
                        "2",
                        ("foo.txt", "bar.txt"),
                    ),
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
                      "bar.txt",
                      "foo.txt"
                    ],
                    "sources_fingerprint": "d3dd0a1f72aaa1fb2623e7024d3ea460b798f6324805cfad5c2b751e2dfb756b",
                    "sources_raw": [
                      "*.txt"
                    ]
                  }
                ]
                """
            ),
            id="single-files-target/exclude-defaults-regression",
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
                    "sources_fingerprint": "b5e73bb1d7a3f8c2e7f8c43f38ab4d198e3512f082c670706df89f5abe319edf",
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
            False,
            dedent(
                """\
                [
                  {
                    "address": "example:files_target",
                    "target_type": "files",
                    "dependencies": [],
                    "sources": [],
                    "sources_fingerprint": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
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
                    _snapshot("", ("foo/a.txt",)),
                    ("foo/a.txt:baz",),
                    dependencies_rules=("does", "apply", "*"),
                    dependents_rules=("fall-through", "*"),
                    applicable_dep_rules=(
                        DependencyRuleApplication(
                            action=DependencyRuleAction.ALLOW,
                            rule_description="foo/BUILD[*] -> foo/BUILD[*]",
                            origin_address=Address("foo", target_name="baz"),
                            origin_type="files",
                            dependency_address=Address(
                                "foo", target_name="baz", relative_file_path="a.txt"
                            ),
                            dependency_type="files",
                        ),
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
                      {
                        "action": "ALLOW",
                        "rule_description": "foo/BUILD[*] -> foo/BUILD[*]",
                        "origin_address": "foo:baz",
                        "origin_type": "files",
                        "dependency_address": "foo/a.txt:baz",
                        "dependency_type": "files"
                      }
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
                    "sources_fingerprint": "72ceef751c940b5797530e298f4d9f66daf3c51f7d075bfb802295ffb01d5de3",
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


def _normalize_fingerprints(tds: Sequence[TargetData]) -> list[TargetData]:
    """We're not here to test the computation of fingerprints."""
    return [
        dataclasses.replace(
            td,
            expanded_sources=None
            if td.expanded_sources is None
            else _snapshot("", td.expanded_sources.files),
        )
        for td in tds
    ]


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

    assert _normalize_fingerprints(tds) == [
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
    assert _normalize_fingerprints(tds) == [
        TargetData(
            FilesGeneratorTarget({"sources": ["*.txt"]}, Address("foo", target_name="baz")),
            _snapshot("", ("foo/a.txt",)),
            ("foo/a.txt:baz",),
            dependencies_rules=("does", "apply", "*"),
            dependents_rules=("fall-through", "*"),
            applicable_dep_rules=(
                DependencyRuleApplication(
                    action=DependencyRuleAction.ALLOW,
                    rule_description="foo/BUILD[*] -> foo/BUILD[*]",
                    origin_address=Address("foo", target_name="baz"),
                    origin_type="files",
                    dependency_address=Address(
                        "foo", target_name="baz", relative_file_path="a.txt"
                    ),
                    dependency_type="files",
                ),
            ),
        ),
        TargetData(
            FileTarget(
                {"source": "a.txt"}, Address("foo", relative_file_path="a.txt", target_name="baz")
            ),
            _snapshot("", ("foo/a.txt",)),
            (),
            dependencies_rules=("does", "apply", "*"),
            dependents_rules=("fall-through", "*"),
            applicable_dep_rules=(),
        ),
    ]
