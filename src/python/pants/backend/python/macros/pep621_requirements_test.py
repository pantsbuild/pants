# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python.target_types import PythonRequirementTarget
from pants.core.target_types import TargetGeneratorSourcesHelperTarget
from pants.engine.addresses import Address
from pants.engine.internals.graph import _TargetParametrizations, _TargetParametrizationsRequest
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error

from .pep621_requirements import PEP621RequirementsTargetGenerator, rules


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *rules(),
            QueryRule(_TargetParametrizations, [_TargetParametrizationsRequest]),
        ],
        target_types=[PEP621RequirementsTargetGenerator],
    )


def assert_python_requirements(
    rule_runner: RuleRunner,
    build_file_entry: str,
    pyproject_toml: str,
    *,
    expected_targets: set[Target],
    pyproject_toml_relpath: str = "pyproject.toml",
) -> None:
    rule_runner.write_files({"BUILD": build_file_entry, pyproject_toml_relpath: pyproject_toml})
    result = rule_runner.request(
        _TargetParametrizations,
        [
            _TargetParametrizationsRequest(
                Address("", target_name="reqs"), description_of_origin="tests"
            )
        ],
    )
    assert set(result.parametrizations.values()) == expected_targets


def test_pyproject_toml(rule_runner: RuleRunner) -> None:
    """This tests that we correctly create a new python_requirement for each entry in a
    pyproject.toml file, where each dependency is unique.

    Some edge cases:
    * We ignore comments and options (values that start with `--`).
    * module_mapping works regardless of capitalization.
    * Projects get normalized thanks to Requirement.parse().
    * Overrides works, including for dependencies and optional-dependencies
    * Optional dependencies are captured as tags
    """
    file_addr = Address("", target_name="reqs", relative_file_path="pyproject.toml")
    assert_python_requirements(
        rule_runner,
        dedent(
            """\
            pep621_requirements(
                name='reqs',
                module_mapping={'ansiCOLORS': ['colors']},
                type_stubs_module_mapping={'Django-types': ['django']},
                overrides={
                  "ansicolors": {"tags": ["overridden"]},
                  "Django": {"dependencies": ["#Django-types"]},
                  "notebook": {"tags": ["another-tag"]},
                },
            )
            """
        ),
        dedent(
            """\
            [project]
            dependencies = [
                # Comment.
                "ansicolors>=1.18.0",
                "Django==3.2 ; python_version>'3'",
                "Django-types",
                "Un-Normalized-PROJECT",  # Inline comment.
                "pip@ git+https://github.com/pypa/pip.git",
            ]
            [project.optional-dependencies]
            test = [
                "pytest>=5.7.0",
            ]
            jupyter = [
                "notebook>=6.1.0",
            ]
            """
        ),
        expected_targets={
            PythonRequirementTarget(
                {
                    "requirements": ["ansicolors>=1.18.0"],
                    "modules": ["colors"],
                    "dependencies": [file_addr.spec],
                    "tags": ["overridden"],
                },
                Address("", target_name="reqs", generated_name="ansicolors"),
            ),
            PythonRequirementTarget(
                {
                    "requirements": ["Django==3.2 ; python_version>'3'"],
                    "dependencies": ["#Django-types", file_addr.spec],
                },
                Address("", target_name="reqs", generated_name="Django"),
            ),
            PythonRequirementTarget(
                {
                    "requirements": ["Django-types"],
                    "type_stub_modules": ["django"],
                    "dependencies": [file_addr.spec],
                },
                Address("", target_name="reqs", generated_name="Django-types"),
            ),
            PythonRequirementTarget(
                {
                    "requirements": ["Un_Normalized_PROJECT"],
                    "dependencies": [file_addr.spec],
                },
                Address("", target_name="reqs", generated_name="Un-Normalized-PROJECT"),
            ),
            PythonRequirementTarget(
                {
                    "requirements": ["pip@ git+https://github.com/pypa/pip.git"],
                    "dependencies": [file_addr.spec],
                },
                Address("", target_name="reqs", generated_name="pip"),
            ),
            PythonRequirementTarget(
                {
                    "requirements": ["pytest>=5.7.0"],
                    "dependencies": [file_addr.spec],
                    "tags": ["test"],
                },
                Address("", target_name="reqs", generated_name="pytest"),
            ),
            PythonRequirementTarget(
                {
                    "requirements": ["notebook>=6.1.0"],
                    "dependencies": [file_addr.spec],
                    "tags": ["another-tag", "jupyter"],
                },
                Address("", target_name="reqs", generated_name="notebook"),
            ),
            TargetGeneratorSourcesHelperTarget({"source": "pyproject.toml"}, file_addr),
        },
    )


def test_multiple_versions(rule_runner: RuleRunner) -> None:
    """This tests that we correctly create a new python_requirement for each unique dependency name
    in a pyproject.toml file, grouping duplicated dependency names to handle multiple requirement
    strings per PEP 508."""
    file_addr = Address("", target_name="reqs", relative_file_path="pyproject.toml")
    assert_python_requirements(
        rule_runner,
        "pep621_requirements(name='reqs')",
        dedent(
            """\
            [project]
            dependencies = [
                "Django>=3.2",
                "Django==3.2.7",
                "confusedmonkey==86",
                "repletewateringcan>=7",
            ]
            """
        ),
        expected_targets={
            PythonRequirementTarget(
                {
                    "requirements": ["Django>=3.2", "Django==3.2.7"],
                    "dependencies": [file_addr.spec],
                },
                Address("", target_name="reqs", generated_name="Django"),
            ),
            PythonRequirementTarget(
                {
                    "requirements": ["confusedmonkey==86"],
                    "dependencies": [file_addr.spec],
                },
                Address("", target_name="reqs", generated_name="confusedmonkey"),
            ),
            PythonRequirementTarget(
                {
                    "requirements": ["repletewateringcan>=7"],
                    "dependencies": [file_addr.spec],
                },
                Address("", target_name="reqs", generated_name="repletewateringcan"),
            ),
            TargetGeneratorSourcesHelperTarget({"source": "pyproject.toml"}, file_addr),
        },
    )


def test_invalid_req(rule_runner: RuleRunner) -> None:
    """Test that we give a nice error message."""
    with engine_error(contains="Invalid requirement 'Not A Valid Req == 3.7' in pyproject.toml"):
        assert_python_requirements(
            rule_runner,
            "pep621_requirements(name='reqs')",
            """[project]\ndependencies = ["Not A Valid Req == 3.7"]""",
            expected_targets=set(),
        )


def test_source_override(rule_runner: RuleRunner) -> None:
    file_addr = Address("", target_name="reqs", relative_file_path="subdir/pyproject.toml")
    assert_python_requirements(
        rule_runner,
        "pep621_requirements(name='reqs', source='subdir/pyproject.toml')",
        "[project]\ndependencies = ['ansicolors>=1.18.0']",
        pyproject_toml_relpath="subdir/pyproject.toml",
        expected_targets={
            PythonRequirementTarget(
                {
                    "requirements": ["ansicolors>=1.18.0"],
                    "dependencies": [file_addr.spec],
                },
                Address("", target_name="reqs", generated_name="ansicolors"),
            ),
            TargetGeneratorSourcesHelperTarget({"source": "subdir/pyproject.toml"}, file_addr),
        },
    )
