# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import Iterable

import pytest

from pants.backend.python.macros.python_requirements_caof import PythonRequirementsCAOF
from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.target_types import PythonRequirementsFileTarget, PythonRequirementTarget
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import AllTargets
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[PythonRequirementTarget, PythonRequirementsFileTarget],
        context_aware_object_factories={"python_requirements": PythonRequirementsCAOF},
        use_deprecated_python_macros=True,
    )


def assert_python_requirements(
    rule_runner: RuleRunner,
    build_file_entry: str,
    requirements_txt: str,
    *,
    expected_file_dep: PythonRequirementsFileTarget,
    expected_targets: Iterable[PythonRequirementTarget],
    requirements_txt_relpath: str = "requirements.txt",
) -> None:
    rule_runner.write_files({"BUILD": build_file_entry, requirements_txt_relpath: requirements_txt})
    targets = rule_runner.request(AllTargets, [])
    assert {expected_file_dep, *expected_targets} == set(targets)


def test_requirements_txt(rule_runner: RuleRunner) -> None:
    """This tests that we correctly create a new python_requirement for each entry in a
    requirements.txt file, where each dependency is unique.

    Some edge cases:
    * We ignore comments and options (values that start with `--`).
    * If a module_mapping is given, and the project is in the map, we copy over a subset of the
      mapping to the created target. It works regardless of capitalization.
    * Projects get normalized thanks to Requirement.parse().
    """
    assert_python_requirements(
        rule_runner,
        dedent(
            """\
            python_requirements(
                module_mapping={'ansiCOLORS': ['colors']},
                type_stubs_module_mapping={'Django-types': ['django']},
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
        expected_file_dep=PythonRequirementsFileTarget(
            {"source": "requirements.txt"},
            Address("", target_name="requirements.txt"),
        ),
        expected_targets=[
            PythonRequirementTarget(
                {
                    "dependencies": [":requirements.txt"],
                    "requirements": [PipRequirement.parse("ansicolors>=1.18.0")],
                    "modules": ["colors"],
                },
                Address("", target_name="ansicolors"),
            ),
            PythonRequirementTarget(
                {
                    "dependencies": [":requirements.txt"],
                    "requirements": [PipRequirement.parse("Django==3.2 ; python_version>'3'")],
                },
                Address("", target_name="Django"),
            ),
            PythonRequirementTarget(
                {
                    "dependencies": [":requirements.txt"],
                    "requirements": [PipRequirement.parse("Django-types")],
                    "type_stub_modules": ["django"],
                },
                Address("", target_name="Django-types"),
            ),
            PythonRequirementTarget(
                {
                    "dependencies": [":requirements.txt"],
                    "requirements": [PipRequirement.parse("Un_Normalized_PROJECT")],
                },
                Address("", target_name="Un-Normalized-PROJECT"),
            ),
            PythonRequirementTarget(
                {
                    "dependencies": [":requirements.txt"],
                    "requirements": [
                        PipRequirement.parse("pip@ git+https://github.com/pypa/pip.git")
                    ],
                },
                Address("", target_name="pip"),
            ),
        ],
    )


def test_multiple_versions(rule_runner: RuleRunner) -> None:
    """This tests that we correctly create a new python_requirement for each unique dependency name
    in a requirements.txt file, grouping duplicated dependency names to handle multiple requirement
    strings per PEP 508."""

    assert_python_requirements(
        rule_runner,
        "python_requirements()",
        dedent(
            """\
            Django>=3.2
            Django==3.2.7
            confusedmonkey==86
            repletewateringcan>=7
            """
        ),
        expected_file_dep=PythonRequirementsFileTarget(
            {"source": "requirements.txt"},
            Address("", target_name="requirements.txt"),
        ),
        expected_targets=[
            PythonRequirementTarget(
                {
                    "dependencies": [":requirements.txt"],
                    "requirements": [
                        PipRequirement.parse("Django>=3.2"),
                        PipRequirement.parse("Django==3.2.7"),
                    ],
                },
                Address("", target_name="Django"),
            ),
            PythonRequirementTarget(
                {
                    "dependencies": [":requirements.txt"],
                    "requirements": [PipRequirement.parse("confusedmonkey==86")],
                },
                Address("", target_name="confusedmonkey"),
            ),
            PythonRequirementTarget(
                {
                    "dependencies": [":requirements.txt"],
                    "requirements": [PipRequirement.parse("repletewateringcan>=7")],
                },
                Address("", target_name="repletewateringcan"),
            ),
        ],
    )


def test_invalid_req(rule_runner: RuleRunner) -> None:
    """Test that we give a nice error message."""
    fake_file_tgt = PythonRequirementsFileTarget(
        {"source": "doesnt matter"}, Address("doesnt_matter")
    )
    with pytest.raises(ExecutionError) as exc:
        assert_python_requirements(
            rule_runner,
            "python_requirements()",
            "\n\nNot A Valid Req == 3.7",
            expected_file_dep=fake_file_tgt,
            expected_targets=[],
        )
    assert "Invalid requirement 'Not A Valid Req == 3.7' in requirements.txt at line 3" in str(
        exc.value
    )

    # Give a nice error message if it looks like they're using pip VCS-style requirements.
    with pytest.raises(ExecutionError) as exc:
        assert_python_requirements(
            rule_runner,
            "python_requirements()",
            "git+https://github.com/pypa/pip.git#egg=pip",
            expected_file_dep=fake_file_tgt,
            expected_targets=[],
        )
    assert "It looks like you're trying to use a pip VCS-style requirement?" in str(exc.value)


def test_source_override(rule_runner: RuleRunner) -> None:
    assert_python_requirements(
        rule_runner,
        "python_requirements(source='subdir/requirements.txt')",
        "ansicolors>=1.18.0",
        requirements_txt_relpath="subdir/requirements.txt",
        expected_file_dep=PythonRequirementsFileTarget(
            {"source": "subdir/requirements.txt"},
            Address("", target_name="subdir_requirements.txt"),
        ),
        expected_targets=[
            PythonRequirementTarget(
                {
                    "dependencies": [":subdir_requirements.txt"],
                    "requirements": [PipRequirement.parse("ansicolors>=1.18.0")],
                },
                Address("", target_name="ansicolors"),
            ),
        ],
    )
