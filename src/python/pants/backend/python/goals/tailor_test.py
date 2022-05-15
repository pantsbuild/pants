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
from pants.backend.python.macros.pipenv_requirements import PipenvRequirementsTargetGenerator
from pants.backend.python.macros.poetry_requirements import PoetryRequirementsTargetGenerator
from pants.backend.python.macros.python_requirements import PythonRequirementsTargetGenerator
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
    rule_runner.set_options(["--no-python-tailor-ignore-solitary-init-files"])
    rule_runner.write_files(
        {
            "3rdparty/Pipfile.lock": "",
            "3rdparty/pyproject.toml": "[tool.poetry]",
            "3rdparty/requirements-test.txt": "",
            "already_owned/requirements.txt": "",
            "already_owned/Pipfile.lock": "",
            "already_owned/pyproject.toml": "[tool.poetry]",
            "no_match/pyproject.toml": "# no poetry section",
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
                    "already_owned/requirements.txt",
                    "already_owned/Pipfile.lock",
                    "already_owned/pyproject.toml",
                    "src/python/foo/bar/__init__.py",
                    "src/python/foo/bar/baz1.py",
                ]
            ),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    PipenvRequirementsTargetGenerator,
                    path="3rdparty",
                    name="Pipfile.lock",
                    triggering_sources=["3rdparty/Pipfile.lock"],
                ),
                PutativeTarget.for_target_type(
                    PoetryRequirementsTargetGenerator,
                    path="3rdparty",
                    name="pyproject.toml",
                    triggering_sources=["3rdparty/pyproject.toml"],
                ),
                PutativeTarget.for_target_type(
                    PythonRequirementsTargetGenerator,
                    path="3rdparty",
                    name="requirements-test.txt",
                    triggering_sources=["3rdparty/requirements-test.txt"],
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


@pytest.mark.parametrize("ignore", [True, False])
def test_ignore_empty_init(rule_runner: RuleRunner, ignore: bool) -> None:
    rule_runner.write_files(
        {
            "project/__init__.py": "",
            "project/d1/__init__.py": "# content",
            "project/d2/__init__.py": "",
            "project/d2/f.py": "",
        }
    )
    rule_runner.set_options([f"--python-tailor-ignore-empty-init-files={ignore}"])
    pts = rule_runner.request(
        PutativeTargets,
        [
            PutativePythonTargetsRequest(PutativeTargetsSearchPaths(("",))),
            AllOwnedSources([]),
        ],
    )
    result = {
        PutativeTarget.for_target_type(
            PythonSourcesGeneratorTarget,
            "project/d1",
            None,
            ["__init__.py"],
        ),
        PutativeTarget.for_target_type(
            PythonSourcesGeneratorTarget,
            "project/d2",
            None,
            ["__init__.py", "f.py"],
        ),
    }
    if not ignore:
        result.add(
            PutativeTarget.for_target_type(
                PythonSourcesGeneratorTarget,
                "project",
                None,
                ["__init__.py"],
            )
        )
    assert result == set(pts)


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
