# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import textwrap

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.goals import tailor
from pants.backend.python.goals.tailor import (
    PutativePythonTargetsRequest,
    classify_source_files,
    is_entry_point,
)
from pants.backend.python.target_types import (
    PexBinary,
    PythonSourcesGeneratorTarget,
    PythonTestsGeneratorTarget,
    PythonTestUtilsGeneratorTarget,
)
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsSearchPaths,
)
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


def test_classify_source_files() -> None:
    test_files = {
        "foo/bar/baz_test.py",
        "foo/test_bar.py",
        "foo/tests.py",
    }
    source_files = {
        "foo/bar/baz.py",
        "foo/bar_baz.py",
        "foo.pyi",
    }
    test_util_files = {
        "conftest.py",
        "foo/bar/baz_test.pyi",
        "foo/test_bar.pyi",
        "tests.pyi",
    }
    assert {
        PythonTestsGeneratorTarget: test_files,
        PythonSourcesGeneratorTarget: source_files,
        PythonTestUtilsGeneratorTarget: test_util_files,
    } == classify_source_files(test_files | source_files | test_util_files)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *tailor.rules(),
            *target_types_rules.rules(),
            QueryRule(PutativeTargets, (PutativePythonTargetsRequest, AllOwnedSources)),
        ],
        target_types=[PexBinary],
    )


def test_find_putative_targets(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        ["--no-python-tailor-ignore-solitary-init-files", "--no-use-deprecated-python-macros"]
    )
    rule_runner.write_files(
        {
            "3rdparty/requirements.txt": "",
            "3rdparty/requirements-test.txt": "",
            **{
                f"src/python/foo/{fp}": ""
                for fp in (
                    "__init__.py",
                    "bar/__init__.py",
                    "bar/baz1.py",
                    "bar/baz1_test.py",
                    "bar/baz2.py",
                    "bar/baz2_test.py",
                    "bar/baz3.py",
                    "bar/conftest.py",
                )
            },
        }
    )
    pts = rule_runner.request(
        PutativeTargets,
        [
            PutativePythonTargetsRequest(PutativeTargetsSearchPaths(("",))),
            AllOwnedSources(
                [
                    "3rdparty/requirements.txt",
                    "src/python/foo/bar/__init__.py",
                    "src/python/foo/bar/baz1.py",
                ]
            ),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget(
                    "3rdparty",
                    "requirements-test.txt",
                    "python_requirements",
                    ("3rdparty/requirements-test.txt",),
                    ("3rdparty/requirements-test.txt",),
                    addressable=True,
                    kwargs={"source": "requirements-test.txt"},
                ),
                PutativeTarget.for_target_type(
                    PythonSourcesGeneratorTarget, "src/python/foo", None, ["__init__.py"]
                ),
                PutativeTarget.for_target_type(
                    PythonSourcesGeneratorTarget,
                    "src/python/foo/bar",
                    None,
                    ["baz2.py", "baz3.py"],
                ),
                PutativeTarget.for_target_type(
                    PythonTestsGeneratorTarget,
                    "src/python/foo/bar",
                    "tests",
                    ["baz1_test.py", "baz2_test.py"],
                ),
                PutativeTarget.for_target_type(
                    PythonTestUtilsGeneratorTarget,
                    "src/python/foo/bar",
                    "test_utils",
                    ["conftest.py"],
                ),
            ]
        )
        == pts
    )


def test_find_putative_targets_subset(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            f"src/python/foo/{fp}": ""
            for fp in (
                "__init__.py",
                "bar/__init__.py",
                "bar/bar.py",
                "bar/bar_test.py",
                "baz/baz.py",
                "baz/baz_test.py",
                "qux/qux.py",
            )
        }
    )
    pts = rule_runner.request(
        PutativeTargets,
        [
            PutativePythonTargetsRequest(
                PutativeTargetsSearchPaths(("src/python/foo/bar", "src/python/foo/qux"))
            ),
            AllOwnedSources(["src/python/foo/bar/__init__.py", "src/python/foo/bar/bar.py"]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    PythonTestsGeneratorTarget,
                    "src/python/foo/bar",
                    "tests",
                    ["bar_test.py"],
                ),
                PutativeTarget.for_target_type(
                    PythonSourcesGeneratorTarget, "src/python/foo/qux", None, ["qux.py"]
                ),
            ]
        )
        == pts
    )


def test_find_putative_targets_for_entry_points(rule_runner: RuleRunner) -> None:
    mains = ("main1.py", "main2.py", "main3.py")
    rule_runner.write_files(
        {
            f"src/python/foo/{name}": textwrap.dedent(
                """
            if __name__ == "__main__":
                main()
            """
            )
            for name in mains
        }
    )
    rule_runner.write_files(
        {
            "src/python/foo/BUILD": (
                "pex_binary(name='main1', entry_point='main1.py')\n"
                "pex_binary(name='main2', entry_point='foo.main2')\n"
            ),
        }
    )
    pts = rule_runner.request(
        PutativeTargets,
        [
            PutativePythonTargetsRequest(PutativeTargetsSearchPaths(("",))),
            AllOwnedSources([f"src/python/foo/{name}" for name in mains]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    PexBinary,
                    "src/python/foo",
                    "main3",
                    [],
                    kwargs={"entry_point": "main3.py"},
                ),
            ]
        )
        == pts
    )


def test_ignore_solitary_init(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            f"src/python/foo/{fp}": ""
            for fp in (
                "__init__.py",
                "bar/__init__.py",
                "bar/bar.py",
                "baz/__init__.py",
                "qux/qux.py",
            )
        }
    )
    pts = rule_runner.request(
        PutativeTargets,
        [
            PutativePythonTargetsRequest(PutativeTargetsSearchPaths(("",))),
            AllOwnedSources([]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    PythonSourcesGeneratorTarget,
                    "src/python/foo/bar",
                    "bar",
                    ["__init__.py", "bar.py"],
                ),
                PutativeTarget.for_target_type(
                    PythonSourcesGeneratorTarget, "src/python/foo/qux", "qux", ["qux.py"]
                ),
            ]
        )
        == pts
    )


def test_is_entry_point_true() -> None:
    assert is_entry_point(
        textwrap.dedent(
            """
    # Note single quotes.
    if __name__ == '__main__':
        main()
    """
        ).encode()
    )

    assert is_entry_point(
        textwrap.dedent(
            """
    # Note double quotes.
    if __name__ == "__main__":
        main()
    """
        ).encode()
    )

    assert is_entry_point(
        textwrap.dedent(
            """
    # Note weird extra spaces.
    if __name__  ==    "__main__":
        main()
    """
        ).encode()
    )

    assert is_entry_point(
        textwrap.dedent(
            """
    # Note trailing comment.
    if __name__ == "__main__": # Trailing comment.
        main()
    """
        ).encode()
    )

    assert is_entry_point(
        textwrap.dedent(
            """
    # Note trailing comment.
    if __name__ == "__main__":# Trailing comment.
        main()
    """
        ).encode()
    )

    assert is_entry_point(
        textwrap.dedent(
            """
    # Note trailing comment.
    if __name__ == "__main__":        # Trailing comment.
        main()
    """
        ).encode()
    )


def test_is_entry_point_false() -> None:
    assert not is_entry_point(
        textwrap.dedent(
            """
    # Note commented out.
    # if __name__ == "__main__":
    #    main()
    """
        ).encode()
    )

    assert not is_entry_point(
        textwrap.dedent(
            """
    # Note weird indent.
     if __name__ == "__main__":
         main()
    """
        ).encode()
    )

    assert not is_entry_point(
        textwrap.dedent(
            """
    # Note some nonsense, as a soundness check.
     print(__name__)
    """
        ).encode()
    )
