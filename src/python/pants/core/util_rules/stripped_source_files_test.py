# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Sequence

import pytest

from pants.core.util_rules import stripped_source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.stripped_source_files import (
    StrippedFileName,
    StrippedFileNameRequest,
    StrippedSourceFileNames,
    StrippedSourceFiles,
)
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_SNAPSHOT
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import MultipleSourcesField, SourcesPathsRequest, Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


class MyMultipleSourcesField(MultipleSourcesField):
    pass


class TargetWithSources(Target):
    alias = "target"
    core_fields = (MyMultipleSourcesField,)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *stripped_source_files.rules(),
            QueryRule(SourceFiles, [SourceFilesRequest]),
            QueryRule(StrippedSourceFiles, [SourceFiles]),
            QueryRule(StrippedSourceFileNames, [SourcesPathsRequest]),
            QueryRule(StrippedFileName, [StrippedFileNameRequest]),
        ],
        target_types=[TargetWithSources],
    )


def get_stripped_files(
    rule_runner: RuleRunner,
    request: SourceFiles,
    *,
    source_root_patterns: Sequence[str] = ("src/python", "src/java", "tests/python"),
) -> list[str]:
    rule_runner.set_options([f"--source-root-patterns={repr(source_root_patterns)}"])
    result = rule_runner.request(StrippedSourceFiles, [request])
    return list(result.snapshot.files)


def test_strip_snapshot(rule_runner: RuleRunner) -> None:
    def get_stripped_files_for_snapshot(
        paths: list[str],
        *,
        source_root_patterns: Sequence[str] = ("src/python", "src/java", "tests/python"),
    ) -> list[str]:
        input_snapshot = rule_runner.make_snapshot_of_empty_files(paths)
        request = SourceFiles(input_snapshot, ())
        return get_stripped_files(rule_runner, request, source_root_patterns=source_root_patterns)

    # Normal source roots
    assert get_stripped_files_for_snapshot(["src/python/project/example.py"]) == [
        "project/example.py"
    ]
    assert get_stripped_files_for_snapshot(
        ["src/python/project/example.py"],
    ) == ["project/example.py"]

    assert get_stripped_files_for_snapshot(["src/java/com/project/example.java"]) == [
        "com/project/example.java"
    ]
    assert get_stripped_files_for_snapshot(["tests/python/project_test/example.py"]) == [
        "project_test/example.py"
    ]

    # Unrecognized source root
    unrecognized_source_root = "no-source-root/example.txt"
    with pytest.raises(ExecutionError) as exc:
        get_stripped_files_for_snapshot([unrecognized_source_root])
    assert f"NoSourceRootError: No source root found for `{unrecognized_source_root}`." in str(
        exc.value
    )

    # Support for multiple source roots
    file_names = ["src/python/project/example.py", "src/java/com/project/example.java"]
    assert get_stripped_files_for_snapshot(file_names) == [
        "com/project/example.java",
        "project/example.py",
    ]

    # Test a source root at the repo root. We have performance optimizations for this case
    # because there is nothing to strip.
    assert get_stripped_files_for_snapshot(
        ["project/f1.py", "project/f2.py"], source_root_patterns=["/"]
    ) == ["project/f1.py", "project/f2.py"]

    assert get_stripped_files_for_snapshot(
        ["dir1/f.py", "dir2/f.py"], source_root_patterns=["/"]
    ) == ["dir1/f.py", "dir2/f.py"]

    # Gracefully handle an empty snapshot
    assert get_stripped_files(rule_runner, SourceFiles(EMPTY_SNAPSHOT, ())) == []


def test_strip_source_file_names(rule_runner: RuleRunner) -> None:
    def assert_stripped_source_file_names(
        address: Address, *, source_root: str, expected: list[str]
    ) -> None:
        rule_runner.set_options([f"--source-root-patterns=['{source_root}']"])
        tgt = rule_runner.get_target(address)
        result = rule_runner.request(
            StrippedSourceFileNames, [SourcesPathsRequest(tgt[MultipleSourcesField])]
        )
        assert set(result) == set(expected)

    rule_runner.write_files(
        {
            "src/java/com/project/example.java": "",
            "src/java/com/project/BUILD": "target(sources=['*.java'])",
            "src/python/script.py": "",
            "src/python/BUILD": "target(sources=['*.py'])",
            "data.json": "",
            # Test a source root at the repo root. We have performance optimizations for this case
            # because there is nothing to strip.
            #
            # Also, gracefully handle an empty sources field.
            "BUILD": "target(name='json', sources=['*.json'])\ntarget(name='empty', sources=[])",
        }
    )
    assert_stripped_source_file_names(
        Address("src/java/com/project"),
        source_root="src/java",
        expected=["com/project/example.java"],
    )
    assert_stripped_source_file_names(
        Address("src/python"), source_root="src/python", expected=["script.py"]
    )
    assert_stripped_source_file_names(
        Address("", target_name="json"), source_root="/", expected=["data.json"]
    )
    assert_stripped_source_file_names(
        Address("", target_name="empty"), source_root="/", expected=[]
    )


@pytest.mark.parametrize("source_root,expected", [("root", "f.txt"), ("/", "root/f.txt")])
def test_strip_file_name(rule_runner: RuleRunner, source_root: str, expected: str) -> None:
    rule_runner.set_options([f"--source-root-patterns=['{source_root}']"])
    result = rule_runner.request(StrippedFileName, [StrippedFileNameRequest("root/f.txt")])
    assert result.value == expected
