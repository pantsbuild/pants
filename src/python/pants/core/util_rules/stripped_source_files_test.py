# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Sequence

import pytest

from pants.core.util_rules import stripped_source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFileNames, StrippedSourceFiles
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_SNAPSHOT
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import Sources, SourcesPathsRequest, Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


class TargetWithSources(Target):
    alias = "target"
    core_fields = (Sources,)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *stripped_source_files.rules(),
            QueryRule(SourceFiles, [SourceFilesRequest]),
            QueryRule(StrippedSourceFiles, [SourceFiles]),
            QueryRule(StrippedSourceFileNames, [SourcesPathsRequest]),
        ],
        target_types=[TargetWithSources],
    )


def get_stripped_files(
    rule_runner: RuleRunner,
    request: SourceFiles,
    *,
    source_root_patterns: Sequence[str] = ("src/python", "src/java", "tests/python"),
) -> List[str]:
    rule_runner.set_options([f"--source-root-patterns={repr(source_root_patterns)}"])
    result = rule_runner.request(StrippedSourceFiles, [request])
    return list(result.snapshot.files)


def test_strip_snapshot(rule_runner: RuleRunner) -> None:
    def get_stripped_files_for_snapshot(
        paths: List[str],
        *,
        source_root_patterns: Sequence[str] = ("src/python", "src/java", "tests/python"),
    ) -> List[str]:
        input_snapshot = rule_runner.make_snapshot_of_empty_files(paths)
        request = SourceFiles(input_snapshot, ())
        return get_stripped_files(rule_runner, request, source_root_patterns=source_root_patterns)

    # Normal source roots
    assert get_stripped_files_for_snapshot(["src/python/project/example.py"]) == [
        "project/example.py"
    ]
    assert (
        get_stripped_files_for_snapshot(
            ["src/python/project/example.py"],
        )
        == ["project/example.py"]
    )

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
        address: Address, *, source_root: str, expected: List[str]
    ) -> None:
        rule_runner.set_options([f"--source-root-patterns=['{source_root}']"])
        tgt = rule_runner.get_target(address)
        result = rule_runner.request(StrippedSourceFileNames, [SourcesPathsRequest(tgt[Sources])])
        assert set(result) == set(expected)

    rule_runner.create_file("src/java/com/project/example.java")
    rule_runner.add_to_build_file("src/java/com/project", "target(sources=['*.java'])")
    assert_stripped_source_file_names(
        Address("src/java/com/project"),
        source_root="src/java",
        expected=["com/project/example.java"],
    )

    rule_runner.create_file("src/python/script.py")
    rule_runner.add_to_build_file("src/python", "target(sources=['*.py'])")
    assert_stripped_source_file_names(
        Address("src/python"), source_root="src/python", expected=["script.py"]
    )

    # Test a source root at the repo root. We have performance optimizations for this case
    # because there is nothing to strip.
    rule_runner.create_file("data.json")
    rule_runner.add_to_build_file("", "target(name='json', sources=['*.json'])\n")
    assert_stripped_source_file_names(
        Address("", target_name="json"), source_root="/", expected=["data.json"]
    )

    # Gracefully handle an empty sources field.
    rule_runner.add_to_build_file("", "target(name='empty', sources=[])")
    assert_stripped_source_file_names(
        Address("", target_name="empty"), source_root="/", expected=[]
    )
