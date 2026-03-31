# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python.goals import lockfile
from pants.backend.python.macros import uv_requirements
from pants.backend.python.macros.uv_requirements import UvRequirementsTargetGenerator
from pants.backend.python.target_types import PythonRequirementTarget
from pants.backend.python.util_rules import pex
from pants.core.target_types import TargetGeneratorSourcesHelperTarget
from pants.engine.addresses import Address
from pants.engine.internals.graph import _TargetParametrizations, _TargetParametrizationsRequest
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *lockfile.rules(),
            *pex.rules(),
            *uv_requirements.rules(),
            QueryRule(_TargetParametrizations, [_TargetParametrizationsRequest]),
        ],
        target_types=[UvRequirementsTargetGenerator],
    )


def assert_uv_requirements(
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
    """
    file_addr = Address("", target_name="reqs", relative_file_path="pyproject.toml")
    assert_uv_requirements(
        rule_runner,
        dedent(
            """\
            uv_requirements(
                name='reqs',
                module_mapping={'ansiCOLORS': ['colors']},
                type_stubs_module_mapping={'Django-types': ['django']},
                overrides={
                  "ansicolors": {"tags": ["overridden"]},
                  "Django": {"dependencies": ["#Django-types"]},
                  "notebook": {"tags": ["another-tag"]},
                },
                source='pyproject.toml',
            )
            """
        ),
        dedent(
            """\
            [tool.uv]
            dev-dependencies = [
                # Comment.
                "",  # Empty line.
                "ansicolors>=1.18.0",
                "coverage>=7.0,<8.0",
                "Django==3.2 ; python_version>'3'",
                "Django-types",
                "Un-Normalized-PROJECT",  # Inline comment.
                "pip@ git+https://github.com/pypa/pip.git",
                "pytest>=5.7.0",
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
                    "requirements": ["coverage>=7.0,<8.0"],
                    "dependencies": [file_addr.spec],
                },
                Address("", target_name="reqs", generated_name="coverage"),
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
                {"requirements": ["Un_Normalized_PROJECT"], "dependencies": [file_addr.spec]},
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
                },
                Address("", target_name="reqs", generated_name="pytest"),
            ),
            PythonRequirementTarget(
                {
                    "requirements": ["notebook>=6.1.0"],
                    "dependencies": [file_addr.spec],
                    "tags": ["another-tag"],
                },
                Address("", target_name="reqs", generated_name="notebook"),
            ),
            TargetGeneratorSourcesHelperTarget({"source": "pyproject.toml"}, file_addr),
        },
    )


def test_invalid_req_pyproject_toml(rule_runner: RuleRunner) -> None:
    """Test that we give a nice error message."""
    with engine_error(contains="Invalid requirement 'Not A Valid Req == 3.7' in pyproject.toml"):
        assert_uv_requirements(
            rule_runner,
            "uv_requirements(name='reqs', source='pyproject.toml')",
            """[tool.uv]\ndev-dependencies = ["Not A Valid Req == 3.7"]""",
            expected_targets=set(),
        )
