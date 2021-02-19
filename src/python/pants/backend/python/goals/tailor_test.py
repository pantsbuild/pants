# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.python.goals import tailor
from pants.backend.python.goals.tailor import (
    PutativePythonTargetsRequest,
    classify_source_files,
    group_by_dir,
)
from pants.backend.python.target_types import PythonLibrary, PythonTests
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.core.util_rules import source_files
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *tailor.rules(),
            *source_files.rules(),
            QueryRule(PutativeTargets, (PutativePythonTargetsRequest, AllOwnedSources)),
        ],
        target_types=[PythonLibrary, PythonTests],
    )


def test_classify_source_files() -> None:
    test_files = {
        "foo/bar/baz_test.py",
        "foo/test_bar.py",
        "foo/tests.py",
        "conftest.py",
        "foo/bar/baz_test.pyi",
        "foo/test_bar.pyi",
        "tests.pyi",
    }
    lib_files = {"foo/bar/baz.py", "foo/bar_baz.py", "foo.pyi"}

    assert {PythonTests: test_files, PythonLibrary: lib_files} == classify_source_files(
        test_files | lib_files
    )


def test_group_by_dir() -> None:
    paths = {
        "foo/bar/baz1.py",
        "foo/bar/baz1_test.py",
        "foo/bar/qux/quux1.py",
        "foo/__init__.py",
        "foo/bar/__init__.py",
        "foo/bar/baz2.py",
        "foo/bar1.py",
        "foo1.py",
        "__init__.py",
    }
    assert {
        "": {"__init__.py", "foo1.py"},
        "foo": {"__init__.py", "bar1.py"},
        "foo/bar": {"__init__.py", "baz1.py", "baz1_test.py", "baz2.py"},
        "foo/bar/qux": {"quux1.py"},
    } == group_by_dir(paths)


def test_find_putative_targets(rule_runner: RuleRunner) -> None:
    for path in [
        "src/python/foo/__init__.py",
        "src/python/foo/bar/BUILD",
        "src/python/foo/bar/__init__.py",
        "src/python/foo/bar/baz1.py",
        "src/python/foo/bar/baz1_test.py",
        "src/python/foo/bar/baz2.py",
        "src/python/foo/bar/baz2_test.py",
        "src/python/foo/bar/baz3.py",
    ]:
        rule_runner.create_file(path)

    pts = rule_runner.request(
        PutativeTargets,
        [
            PutativePythonTargetsRequest(),
            AllOwnedSources(["src/python/foo/bar/__init__.py", "src/python/foo/bar/baz1.py"]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    PythonLibrary, "src/python/foo", "foo", ["__init__.py"]
                ),
                PutativeTarget.for_target_type(
                    PythonLibrary, "src/python/foo/bar", "bar", ["baz2.py", "baz3.py"]
                ),
                PutativeTarget.for_target_type(
                    PythonTests,
                    "src/python/foo/bar",
                    "tests",
                    ["baz1_test.py", "baz2_test.py"],
                    kwargs={"name": "tests"},
                ),
            ]
        )
        == pts
    )
