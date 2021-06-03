# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import Iterable

import pytest
from pkg_resources import Requirement

from pants.backend.python.macros.poetry_requirement import PoetryRequirements
from pants.backend.python.target_types import PythonRequirementLibrary, PythonRequirementsFile
from pants.base.specs import AddressSpecs, DescendantAddresses, FilesystemSpecs, Specs
from pants.engine.addresses import Address
from pants.engine.target import Targets
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[QueryRule(Targets, (Specs,))],
        target_types=[PythonRequirementLibrary, PythonRequirementsFile],
        context_aware_object_factories={"python_requirements": PoetryRequirements},
    )


def assert_python_requirements(
    rule_runner: RuleRunner,
    build_file_entry: str,
    pyproject_toml: str,
    *,
    expected_file_dep: PythonRequirementsFile,
    expected_targets: Iterable[PythonRequirementLibrary],
    pyproject_toml_relpath: str = "pyproject.toml",
) -> None:
    rule_runner.add_to_build_file("", f"{build_file_entry}\n")
    rule_runner.create_file(pyproject_toml_relpath, pyproject_toml)
    targets = rule_runner.request(
        Targets,
        [Specs(AddressSpecs([DescendantAddresses("")]), FilesystemSpecs([]))],
    )
    assert {expected_file_dep, *expected_targets} == set(targets)


def test_pyproject_toml(rule_runner: RuleRunner) -> None:
    """This tests that we correctly create a new python_requirement_library for each entry in a
    pyproject.toml file.

    Note that this just ensures proper targets are created; whether or not all dependencies are
    parsed are checked in tests found in poetry_project_test.py.
    """
    assert_python_requirements(
        rule_runner,
        "python_requirements(module_mapping={'ansicolors': ['colors']})",
        dedent(
            """\
            [tool.poetry.dependencies]
            Django = {version = "3.2", python = "3"}
            ansicolors = ">=1.18.0"
            Un-Normalized-PROJECT = "1.0.0"
            [tool.poetry.dev-dependencies]
            """
        ),
        expected_file_dep=PythonRequirementsFile(
            {"sources": ["pyproject.toml"]},
            address=Address("", target_name="pyproject.toml"),
        ),
        expected_targets=[
            PythonRequirementLibrary(
                {
                    "dependencies": [":pyproject.toml"],
                    "requirements": [Requirement.parse("ansicolors>=1.18.0")],
                    "module_mapping": {"ansicolors": ["colors"]},
                },
                address=Address("", target_name="ansicolors"),
            ),
            PythonRequirementLibrary(
                {
                    "dependencies": [":pyproject.toml"],
                    "requirements": [Requirement.parse("Django==3.2 ; python_version == '3'")],
                },
                address=Address("", target_name="Django"),
            ),
            PythonRequirementLibrary(
                {
                    "dependencies": [":pyproject.toml"],
                    "requirements": [Requirement.parse("Un_Normalized_PROJECT == 1.0.0")],
                },
                address=Address("", target_name="Un-Normalized-PROJECT"),
            ),
        ],
    )


def test_relpath_override(rule_runner: RuleRunner) -> None:
    assert_python_requirements(
        rule_runner,
        "python_requirements(pyproject_toml_relpath='subdir/pyproject.toml')",
        dedent(
            """\
            [tool.poetry.dependencies]
            ansicolors = ">=1.18.0"
            [tool.poetry.dev-dependencies]
            """
        ),
        pyproject_toml_relpath="subdir/pyproject.toml",
        expected_file_dep=PythonRequirementsFile(
            {"sources": ["subdir/pyproject.toml"]},
            address=Address("", target_name="subdir_pyproject.toml"),
        ),
        expected_targets=[
            PythonRequirementLibrary(
                {
                    "dependencies": [":subdir_pyproject.toml"],
                    "requirements": [Requirement.parse("ansicolors>=1.18.0")],
                },
                address=Address("", target_name="ansicolors"),
            ),
        ],
    )


# TODO: tests currently broken; fix/finish & add appropriate error handling.
def test_bad_version(rule_runner: RuleRunner, capf) -> None:
    assert_python_requirements(
        rule_runner,
        "python_requirements()",
        """
        [tool.poetry.dependencies]
        foo = "~r62b"
        [tool.poetry.dev-dependencies]
        """,
        expected_file_dep=PythonRequirementsFile(
            {"sources": ["pyproject.toml"]},
            address=Address("", target_name="pyproject.toml"),
        ),
        expected_targets=[
            PythonRequirementLibrary(
                {
                    "dependencies": [":pyproject.toml"],
                    "requirements": [Requirement.parse("foo <r62b,>=r62b")],
                },
                address=Address("", target_name="foo"),
            )
        ],
    )


def test_bad_toml_format() -> None:
    pass
