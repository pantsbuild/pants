# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.goals import tailor
from pants.backend.python.goals.tailor import PutativePythonTargetsRequest, classify_source_files
from pants.backend.python.target_types import PythonLibrary, PythonTests
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


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


def test_find_putative_targets() -> None:
    rule_runner = RuleRunner(
        rules=[
            *tailor.rules(),
            QueryRule(PutativeTargets, (PutativePythonTargetsRequest, AllOwnedSources)),
        ],
        target_types=[],
    )
    rule_runner.write_files(
        {
            f"src/python/foo/{fp}": ""
            for fp in (
                "__init__.py",
                "bar/__init__.py",
                "bar/baz1.py",
                "bar/baz1_test.py",
                "bar/baz2.py",
                "bar/baz2_test.py",
                "bar/baz3.py",
            )
        }
    )
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
