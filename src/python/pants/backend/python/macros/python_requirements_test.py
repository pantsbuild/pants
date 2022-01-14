# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python.macros import python_requirements
from pants.backend.python.macros.python_requirements import (
    GenerateFromPythonRequirementsRequest,
    PythonRequirementsTargetGenerator,
)
from pants.backend.python.target_types import PythonRequirementsFileTarget, PythonRequirementTarget
from pants.engine.addresses import Address
from pants.engine.target import GeneratedTargets, Target
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *python_requirements.rules(),
            QueryRule(GeneratedTargets, [GenerateFromPythonRequirementsRequest]),
        ],
        target_types=[PythonRequirementsTargetGenerator],
    )


def assert_python_requirements(
    rule_runner: RuleRunner,
    build_file_entry: str,
    requirements_txt: str,
    *,
    expected_targets: set[Target],
    requirements_txt_relpath: str = "requirements.txt",
) -> None:
    rule_runner.write_files({"BUILD": build_file_entry, requirements_txt_relpath: requirements_txt})
    generator = rule_runner.get_target(Address("", target_name="reqs"))
    result = rule_runner.request(
        GeneratedTargets, [GenerateFromPythonRequirementsRequest(generator)]
    )
    assert set(result.values()) == expected_targets


def test_requirements_txt(rule_runner: RuleRunner) -> None:
    """This tests that we correctly create a new python_requirement for each entry in a
    requirements.txt file, where each dependency is unique.

    Some edge cases:
    * We ignore comments and options (values that start with `--`).
    * module_mapping works regardless of capitalization.
    * Projects get normalized thanks to Requirement.parse().
    * Overrides works, including for dependencies.
    """
    file_addr = Address("", target_name="reqs", relative_file_path="requirements.txt")
    assert_python_requirements(
        rule_runner,
        dedent(
            """\
            python_requirements(
                name='reqs',
                module_mapping={'ansiCOLORS': ['colors']},
                type_stubs_module_mapping={'Django-types': ['django']},
                overrides={
                  "ansicolors": {"tags": ["overridden"]},
                  "Django": {"dependencies": ["#Django-types"]},
                },
            )
            """
        ),
        dedent(
            """\
            # Comment.
            --find-links=https://duckduckgo.com
            ansicolors>=1.18.0
            Django==3.2 ; python_version>'3'
            Django-types
            Un-Normalized-PROJECT  # Inline comment.
            pip@ git+https://github.com/pypa/pip.git
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
            PythonRequirementsFileTarget({"source": "requirements.txt"}, file_addr),
        },
    )


def test_multiple_versions(rule_runner: RuleRunner) -> None:
    """This tests that we correctly create a new python_requirement for each unique dependency name
    in a requirements.txt file, grouping duplicated dependency names to handle multiple requirement
    strings per PEP 508."""
    file_addr = Address("", target_name="reqs", relative_file_path="requirements.txt")
    assert_python_requirements(
        rule_runner,
        "python_requirements(name='reqs')",
        dedent(
            """\
            Django>=3.2
            Django==3.2.7
            confusedmonkey==86
            repletewateringcan>=7
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
                {"requirements": ["confusedmonkey==86"], "dependencies": [file_addr.spec]},
                Address("", target_name="reqs", generated_name="confusedmonkey"),
            ),
            PythonRequirementTarget(
                {"requirements": ["repletewateringcan>=7"], "dependencies": [file_addr.spec]},
                Address("", target_name="reqs", generated_name="repletewateringcan"),
            ),
            PythonRequirementsFileTarget({"source": "requirements.txt"}, file_addr),
        },
    )


def test_invalid_req(rule_runner: RuleRunner) -> None:
    """Test that we give a nice error message."""
    with engine_error(
        contains="Invalid requirement 'Not A Valid Req == 3.7' in requirements.txt at line 3"
    ):
        assert_python_requirements(
            rule_runner,
            "python_requirements(name='reqs')",
            "\n\nNot A Valid Req == 3.7",
            expected_targets=set(),
        )

    # Give a nice error message if it looks like they're using pip VCS-style requirements.
    with engine_error(contains="It looks like you're trying to use a pip VCS-style requirement?"):
        assert_python_requirements(
            rule_runner,
            "python_requirements(name='reqs')",
            "git+https://github.com/pypa/pip.git#egg=pip",
            expected_targets=set(),
        )


def test_source_override(rule_runner: RuleRunner) -> None:
    file_addr = Address("", target_name="reqs", relative_file_path="subdir/requirements.txt")
    assert_python_requirements(
        rule_runner,
        "python_requirements(name='reqs', source='subdir/requirements.txt')",
        "ansicolors>=1.18.0",
        requirements_txt_relpath="subdir/requirements.txt",
        expected_targets={
            PythonRequirementTarget(
                {"requirements": ["ansicolors>=1.18.0"], "dependencies": [file_addr.spec]},
                Address("", target_name="reqs", generated_name="ansicolors"),
            ),
            PythonRequirementsFileTarget({"source": "subdir/requirements.txt"}, file_addr),
        },
    )
