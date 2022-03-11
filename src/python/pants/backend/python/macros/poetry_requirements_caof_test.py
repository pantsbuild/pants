# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Any, Iterable

import pytest

from pants.backend.python.macros.poetry_requirements_caof import PoetryRequirementsCAOF
from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.target_types import PythonRequirementTarget
from pants.core.target_types import TargetGeneratorSourcesHelperTarget
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import AllTargets
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[PythonRequirementTarget, TargetGeneratorSourcesHelperTarget],
        context_aware_object_factories={"poetry_requirements": PoetryRequirementsCAOF},
        use_deprecated_python_macros=True,
    )


def assert_poetry_requirements(
    rule_runner: RuleRunner,
    build_file_entry: str,
    pyproject_toml: str,
    *,
    expected_file_dep: TargetGeneratorSourcesHelperTarget,
    expected_targets: Iterable[PythonRequirementTarget],
    pyproject_toml_relpath: str = "pyproject.toml",
) -> None:
    rule_runner.write_files({"BUILD": build_file_entry, pyproject_toml_relpath: pyproject_toml})
    targets = rule_runner.request(AllTargets, [])
    assert {expected_file_dep, *expected_targets} == set(targets)


def test_pyproject_toml(rule_runner: RuleRunner) -> None:
    """This tests that we correctly create a new python_requirement for each entry in a
    pyproject.toml file.

    Note that this just ensures proper targets are created; see prior tests for specific parsing
    edge cases.
    """
    assert_poetry_requirements(
        rule_runner,
        dedent(
            """\
            poetry_requirements(
                # module_mapping should work regardless of capitalization.
                module_mapping={'ansiCOLORS': ['colors']},
                type_stubs_module_mapping={'Django-types': ['django']},
            )
            """
        ),
        dedent(
            """\
            [tool.poetry.dependencies]
            Django = {version = "3.2", python = "3"}
            Django-types = "2"
            Un-Normalized-PROJECT = "1.0.0"
            [tool.poetry.dev-dependencies]
            ansicolors = ">=1.18.0"
            """
        ),
        expected_file_dep=TargetGeneratorSourcesHelperTarget(
            {"sources": ["pyproject.toml"]},
            address=Address("", target_name="pyproject.toml"),
        ),
        expected_targets=[
            PythonRequirementTarget(
                {
                    "dependencies": [":pyproject.toml"],
                    "requirements": [PipRequirement.parse("ansicolors>=1.18.0")],
                    "modules": ["colors"],
                },
                address=Address("", target_name="ansicolors"),
            ),
            PythonRequirementTarget(
                {
                    "dependencies": [":pyproject.toml"],
                    "requirements": [PipRequirement.parse("Django==3.2 ; python_version == '3'")],
                },
                address=Address("", target_name="Django"),
            ),
            PythonRequirementTarget(
                {
                    "dependencies": [":pyproject.toml"],
                    "requirements": [PipRequirement.parse("Django-types==2")],
                    "type_stub_modules": ["django"],
                },
                address=Address("", target_name="Django-types"),
            ),
            PythonRequirementTarget(
                {
                    "dependencies": [":pyproject.toml"],
                    "requirements": [PipRequirement.parse("Un_Normalized_PROJECT == 1.0.0")],
                },
                address=Address("", target_name="Un-Normalized-PROJECT"),
            ),
        ],
    )


def test_source_override(rule_runner: RuleRunner) -> None:
    assert_poetry_requirements(
        rule_runner,
        "poetry_requirements(source='subdir/pyproject.toml')",
        dedent(
            """\
            [tool.poetry.dependencies]
            ansicolors = ">=1.18.0"
            [tool.poetry.dev-dependencies]
            """
        ),
        pyproject_toml_relpath="subdir/pyproject.toml",
        expected_file_dep=TargetGeneratorSourcesHelperTarget(
            {"sources": ["subdir/pyproject.toml"]},
            address=Address("", target_name="subdir_pyproject.toml"),
        ),
        expected_targets=[
            PythonRequirementTarget(
                {
                    "dependencies": [":subdir_pyproject.toml"],
                    "requirements": [PipRequirement.parse("ansicolors>=1.18.0")],
                },
                address=Address("", target_name="ansicolors"),
            ),
        ],
    )


def test_non_pep440_error(rule_runner: RuleRunner, caplog: Any) -> None:
    with pytest.raises(ExecutionError) as exc:
        assert_poetry_requirements(
            rule_runner,
            "poetry_requirements()",
            """
            [tool.poetry.dependencies]
            foo = "~r62b"
            [tool.poetry.dev-dependencies]
            """,
            expected_file_dep=TargetGeneratorSourcesHelperTarget(
                {"sources": ["pyproject.toml"]},
                address=Address("", target_name="pyproject.toml"),
            ),
            expected_targets=[],
        )
    assert 'Failed to parse requirement foo = "~r62b" in pyproject.toml' in str(exc.value)


def test_no_req_defined_warning(rule_runner: RuleRunner, caplog: Any) -> None:
    assert_poetry_requirements(
        rule_runner,
        "poetry_requirements()",
        """
        [tool.poetry.dependencies]
        [tool.poetry.dev-dependencies]
        """,
        expected_file_dep=TargetGeneratorSourcesHelperTarget(
            {"sources": ["pyproject.toml"]},
            address=Address("", target_name="pyproject.toml"),
        ),
        expected_targets=[],
    )
    assert "No requirements defined" in caplog.text


def test_bad_dict_format(rule_runner: RuleRunner) -> None:
    with pytest.raises(ExecutionError) as exc:
        assert_poetry_requirements(
            rule_runner,
            "poetry_requirements()",
            """
            [tool.poetry.dependencies]
            foo = {bad_req = "test"}
            [tool.poetry.dev-dependencies]
            """,
            expected_file_dep=TargetGeneratorSourcesHelperTarget(
                {"sources": ["pyproject.toml"]},
                address=Address("", target_name="pyproject.toml"),
            ),
            expected_targets=[],
        )
    assert "not formatted correctly; at" in str(exc.value)


def test_bad_req_type(rule_runner: RuleRunner) -> None:
    with pytest.raises(ExecutionError) as exc:
        assert_poetry_requirements(
            rule_runner,
            "poetry_requirements()",
            """
            [tool.poetry.dependencies]
            foo = 4
            [tool.poetry.dev-dependencies]
            """,
            expected_file_dep=TargetGeneratorSourcesHelperTarget(
                {"sources": ["pyproject.toml"]},
                address=Address("", target_name="pyproject.toml"),
            ),
            expected_targets=[],
        )
    assert "was of type int" in str(exc.value)


def test_no_tool_poetry(rule_runner: RuleRunner) -> None:
    with pytest.raises(ExecutionError) as exc:
        assert_poetry_requirements(
            rule_runner,
            "poetry_requirements()",
            """
            foo = 4
            """,
            expected_file_dep=TargetGeneratorSourcesHelperTarget(
                {"sources": ["pyproject.toml"]},
                address=Address("", target_name="pyproject.toml"),
            ),
            expected_targets=[],
        )
    assert "`tool.poetry` found in pyproject.toml" in str(exc.value)
