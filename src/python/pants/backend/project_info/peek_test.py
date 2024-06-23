# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
from textwrap import dedent
from typing import Sequence, cast

import pytest

from pants.backend.project_info import peek
from pants.backend.project_info.peek import (
    AdditionalTargetData,
    HasAdditionalTargetDataFieldSet,
    Peek,
    TargetData,
    TargetDatas,
)
from pants.backend.visibility.rules import rules as visibility_rules
from pants.base.specs import RawSpecs, RecursiveGlobSpec
from pants.core.target_types import (
    ArchiveTarget,
    FilesGeneratorTarget,
    FileSourceField,
    FileTarget,
    GenericTarget,
)
from pants.engine.addresses import Address
from pants.engine.fs import Snapshot
from pants.engine.internals.dep_rules import DependencyRuleAction, DependencyRuleApplication
from pants.engine.rules import QueryRule, rule
from pants.engine.target import DescriptionField
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner


def _snapshot(fingerprint: str, files: tuple[str, ...]) -> Snapshot:
    return Snapshot.create_for_testing(files, ())


@dataclasses.dataclass(frozen=True)
class FirstFakeAdditionalTargetDataFieldSet(HasAdditionalTargetDataFieldSet):
    required_fields = (FileSourceField,)

    source: FileSourceField


@dataclasses.dataclass(frozen=True)
class SecondFakeAdditionalTargetDataFieldSet(HasAdditionalTargetDataFieldSet):
    required_fields = (FileSourceField, DescriptionField)

    description: DescriptionField


@rule
async def first_fake_additional_target_data(
    field_set: FirstFakeAdditionalTargetDataFieldSet,
) -> AdditionalTargetData:
    filename, extension = cast(str, field_set.source.value).split(".", 1)
    return AdditionalTargetData("source_parts", {"filename": filename, "extension": extension})


@rule
async def second_fake_additional_target_data(
    field_set: SecondFakeAdditionalTargetDataFieldSet,
) -> AdditionalTargetData:
    return AdditionalTargetData(
        "reversed_description",
        field_set.description.value[::-1] if field_set.description.value else None,
    )


def test_render_json_null_case():
    assert peek.render_json([]) == "[]\n"


def test_render_json_with_single_target():
    target_data = TargetData(
        FilesGeneratorTarget(
            {"sources": ["foo.txt"]}, Address("example", target_name="files_target")
        ),
        _snapshot("1", ("foo.txt",)),
        tuple(),
    )
    expected = dedent(
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
    )
    actual = peek.render_json([target_data])
    assert actual == expected


def test_render_json_with_multiple_targets_and_goals_excluding_defaults():
    target_data = [
        TargetData(
            FilesGeneratorTarget(
                {"sources": ["*.txt"], "tags": ["zippable"]},
                Address("example", target_name="files_target"),
            ),
            _snapshot("0", ()),
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
            goals=("package",),
        ),
    ]
    expected = dedent(
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
            "goals": [
              "package"
            ],
            "output_path": "my-archive.zip"
          }
        ]
        """
    )

    actual = peek.render_json(target_data, exclude_defaults=True)
    assert actual == expected


def test_render_json_with_single_target_excluding_defaults_regression():
    target_data = TargetData(
        FilesGeneratorTarget(
            {
                "sources": ["*.txt"],
                # Regression test that we can handle a dict with `tuple[str, ...]` as
                # key.
                "overrides": {("foo.txt",): {"tags": ["overridden"]}},
            },
            Address("example", target_name="files_target"),
        ),
        _snapshot("2", ("foo.txt", "bar.txt")),
        tuple(),
    )
    expected = dedent(
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
    )

    actual = peek.render_json([target_data], exclude_defaults=True)
    assert actual == expected


def test_render_json_including_dep_rules():
    target_data = [
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
    ]
    expected = dedent(
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
    )

    actual = peek.render_json(target_data, exclude_defaults=True, include_dep_rules=True)
    assert actual == expected


def test_render_json_including_additional_info():
    target_data = TargetData(
        FilesGeneratorTarget(
            {"sources": ["foo.txt"]}, Address("example", target_name="files_target")
        ),
        _snapshot("1", ("foo.txt",)),
        tuple(),
        additional_info=(
            AdditionalTargetData("test_data1", {"hello": "world"}),
            AdditionalTargetData("test_data2", ["one", "two"]),
        ),
    )
    expected = dedent(
        """\
        [
          {
            "address": "example:files_target",
            "target_type": "files",
            "additional_info": {
              "test_data1": {
                "hello": "world"
              },
              "test_data2": [
                "one",
                "two"
              ]
            },
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
    )

    actual = peek.render_json([target_data])
    assert actual == expected


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *peek.rules(),
            *visibility_rules(),
            UnionRule(HasAdditionalTargetDataFieldSet, FirstFakeAdditionalTargetDataFieldSet),
            UnionRule(HasAdditionalTargetDataFieldSet, SecondFakeAdditionalTargetDataFieldSet),
            first_fake_additional_target_data,
            second_fake_additional_target_data,
            QueryRule(TargetDatas, [RawSpecs]),
            QueryRule(AdditionalTargetData, [FirstFakeAdditionalTargetDataFieldSet]),
            QueryRule(AdditionalTargetData, [SecondFakeAdditionalTargetDataFieldSet]),
        ],
        target_types=[FilesGeneratorTarget, GenericTarget, FileTarget],
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


def test_get_target_data_with_additional_info(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--peek-include-additional-info"])
    rule_runner.write_files(
        {
            "foo/BUILD": dedent(
                """\
            file(source="a.txt", description="reverse me!")
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
            FileTarget(
                {"source": "a.txt", "description": "reverse me!"},
                Address("foo", target_name="foo"),
                name_explicitly_set=False,
            ),
            _snapshot("", ("foo/a.txt",)),
            (),
            additional_info=(
                AdditionalTargetData("source_parts", {"filename": "a", "extension": "txt"}),
                AdditionalTargetData("reversed_description", "reverse me!"[::-1]),
            ),
        ),
    ]
