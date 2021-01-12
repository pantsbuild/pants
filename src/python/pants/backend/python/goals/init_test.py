# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.python.goals import init
from pants.backend.python.goals.init import (
    PutativePythonTargetsRequest,
    classify_source_files,
    group_by_dir,
)
from pants.backend.python.target_types import PythonLibrary, PythonTests
from pants.core.goals.init import PutativeTarget, PutativeTargets
from pants.core.util_rules import source_files
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *init.rules(),
            *source_files.rules(),
            QueryRule(PutativeTargets, (PutativePythonTargetsRequest,)),
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

    assert {PythonTests.alias: test_files, PythonLibrary.alias: lib_files} == classify_source_files(
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
    dir_structure = {
        "src/python/foo/__init__.py": "",
        "src/python/foo/bar/BUILD": "python_library(sources=['__init__.py', 'baz1.py'])",
        "src/python/foo/bar/__init__.py": "",
        "src/python/foo/bar/baz1.py": "",
        "src/python/foo/bar/baz1_test.py": "",
        "src/python/foo/bar/baz2.py": "",
        "src/python/foo/bar/baz2_test.py": "",
        "src/python/foo/bar/baz3.py": "",
    }

    for path, content in dir_structure.items():
        rule_runner.create_file(path, content)

    pts = rule_runner.request(PutativeTargets, [PutativePythonTargetsRequest()])
    assert (
        PutativeTargets(
            [
                PutativeTarget("src/python/foo", "foo", "python_library", ["__init__.py"]),
                PutativeTarget(
                    "src/python/foo/bar", "bar", "python_library", ["baz2.py", "baz3.py"]
                ),
                PutativeTarget(
                    "src/python/foo/bar",
                    "tests",
                    "python_tests",
                    ["baz1_test.py", "baz2_test.py"],
                    kwargs={"name": "tests"},
                ),
            ]
        )
        == pts
    )
