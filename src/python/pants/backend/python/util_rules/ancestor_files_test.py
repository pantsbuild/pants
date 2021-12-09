# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.python.util_rules import ancestor_files
from pants.backend.python.util_rules.ancestor_files import (
    AncestorFiles,
    AncestorFilesRequest,
    putative_ancestor_files,
)
from pants.engine.fs import DigestContents
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *ancestor_files.rules(),
            QueryRule(AncestorFiles, (AncestorFilesRequest,)),
        ]
    )


def assert_injected(
    rule_runner: RuleRunner,
    *,
    source_roots: list[str],
    original_declared_files: list[str],
    original_undeclared_files: list[str],
    expected_discovered: list[str],
) -> None:
    rule_runner.set_options([f"--source-root-patterns={source_roots}"])
    rule_runner.write_files(
        {
            **{f: "# undeclared" for f in original_undeclared_files},
            **{f: "# declared" for f in original_declared_files},
        }
    )
    request = AncestorFilesRequest(
        requested=("__init__.py",), input_files=tuple(original_declared_files)
    )
    result = rule_runner.request(AncestorFiles, [request]).snapshot
    assert list(result.files) == sorted(expected_discovered)

    materialized_result = rule_runner.request(DigestContents, [result.digest])
    for file_content in materialized_result:
        path = file_content.path
        if not path.endswith("__init__.py"):
            continue
        assert path in original_declared_files or path in expected_discovered
        expected = b"# declared" if path in original_declared_files else b"# undeclared"
        assert file_content.content == expected


def test_unstripped(rule_runner: RuleRunner) -> None:
    assert_injected(
        rule_runner,
        source_roots=["src/python", "tests/python"],
        original_declared_files=[
            "src/python/project/lib.py",
            "src/python/project/subdir/__init__.py",
            "src/python/project/subdir/lib.py",
            "src/python/no_init/lib.py",
        ],
        original_undeclared_files=[
            "src/python/__init__.py",
            "src/python/project/__init__.py",
            "tests/python/project/__init__.py",
        ],
        expected_discovered=["src/python/__init__.py", "src/python/project/__init__.py"],
    )


def test_unstripped_source_root_at_buildroot(rule_runner: RuleRunner) -> None:
    assert_injected(
        rule_runner,
        source_roots=["/"],
        original_declared_files=[
            "project/lib.py",
            "project/subdir/__init__.py",
            "project/subdir/lib.py",
            "no_init/lib.py",
        ],
        original_undeclared_files=[
            "__init__.py",
            "project/__init__.py",
        ],
        expected_discovered=["__init__.py", "project/__init__.py"],
    )


def test_identify_missing_ancestor_files() -> None:
    assert {
        "__init__.py",
        "a/__init__.py",
        "a/b/__init__.py",
        "a/b/c/d/__init__.py",
    } == putative_ancestor_files(
        requested=("__init__.py",),
        input_files=("a/b/foo.py", "a/b/c/__init__.py", "a/b/c/d/bar.py", "a/e/__init__.py"),
    )

    assert {
        "__init__.py",
        "src/__init__.py",
        "src/python/__init__.py",
        "src/python/a/__init__.py",
        "src/python/a/b/__init__.py",
        "src/python/a/b/c/d/__init__.py",
    } == putative_ancestor_files(
        requested=("__init__.py",),
        input_files=(
            "src/python/a/b/foo.py",
            "src/python/a/b/c/__init__.py",
            "src/python/a/b/c/d/bar.py",
            "src/python/a/e/__init__.py",
        ),
    )

    assert putative_ancestor_files(requested=("f.py", "f.pyi"), input_files=("subdir/foo.py",)) == {
        "f.py",
        "f.pyi",
        "subdir/f.py",
        "subdir/f.pyi",
    }
    assert putative_ancestor_files(
        requested=("f.py", "f.pyi"), input_files=("subdir/foo.pyi",)
    ) == {"f.py", "f.pyi", "subdir/f.py", "subdir/f.pyi"}
