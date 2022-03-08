# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from json import dumps
from textwrap import dedent
from typing import Iterable

import pytest

from pants.backend.python.macros.pipenv_requirements_caof import PipenvRequirementsCAOF
from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.target_types import PythonRequirementTarget
from pants.core.target_types import TargetGeneratorSourcesHelperTarget
from pants.engine.addresses import Address
from pants.engine.target import AllTargets
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[PythonRequirementTarget, TargetGeneratorSourcesHelperTarget],
        context_aware_object_factories={"pipenv_requirements": PipenvRequirementsCAOF},
        use_deprecated_python_macros=True,
    )


def assert_pipenv_requirements(
    rule_runner: RuleRunner,
    build_file_entry: str,
    pipfile_lock: dict,
    *,
    expected_file_dep: TargetGeneratorSourcesHelperTarget,
    expected_targets: Iterable[PythonRequirementTarget],
    pipfile_lock_relpath: str = "Pipfile.lock",
) -> None:
    rule_runner.write_files({"BUILD": build_file_entry, pipfile_lock_relpath: dumps(pipfile_lock)})
    targets = rule_runner.request(AllTargets, [])
    assert {expected_file_dep, *expected_targets} == set(targets)


def test_pipfile_lock(rule_runner: RuleRunner) -> None:
    """This tests that we correctly create a new `python_requirement` target for each entry in a
    Pipfile.lock file.

    Edge cases:
    * Develop and Default requirements are used
    * If a module_mapping is given, and the project is in the map, we set `modules`. It
      works regardless of capitalization.
    """
    assert_pipenv_requirements(
        rule_runner,
        "pipenv_requirements(module_mapping={'ANSIcolors': ['colors']})",
        {
            "default": {"ansicolors": {"version": ">=1.18.0"}},
            "develop": {"cachetools": {"markers": "python_version ~= '3.5'", "version": "==4.1.1"}},
        },
        expected_file_dep=TargetGeneratorSourcesHelperTarget(
            {"sources": ["Pipfile.lock"]}, Address("", target_name="Pipfile.lock")
        ),
        expected_targets=[
            PythonRequirementTarget(
                {
                    "requirements": [PipRequirement.parse("ansicolors>=1.18.0")],
                    "dependencies": [":Pipfile.lock"],
                    "modules": ["colors"],
                },
                Address("", target_name="ansicolors"),
            ),
            PythonRequirementTarget(
                {
                    "requirements": [
                        PipRequirement.parse("cachetools==4.1.1;python_version ~= '3.5'")
                    ],
                    "dependencies": [":Pipfile.lock"],
                },
                Address("", target_name="cachetools"),
            ),
        ],
    )


def test_properly_creates_extras_requirements(rule_runner: RuleRunner) -> None:
    """This tests the proper parsing of requirements installed with specified extras."""
    assert_pipenv_requirements(
        rule_runner,
        "pipenv_requirements()",
        {
            "default": {"ansicolors": {"version": ">=1.18.0", "extras": ["neon"]}},
            "develop": {
                "cachetools": {
                    "markers": "python_version ~= '3.5'",
                    "version": "==4.1.1",
                    "extras": ["ring", "mongo"],
                }
            },
        },
        expected_file_dep=TargetGeneratorSourcesHelperTarget(
            {"sources": ["Pipfile.lock"]}, Address("", target_name="Pipfile.lock")
        ),
        expected_targets=[
            PythonRequirementTarget(
                {
                    "requirements": [PipRequirement.parse("ansicolors[neon]>=1.18.0")],
                    "dependencies": [":Pipfile.lock"],
                },
                Address("", target_name="ansicolors"),
            ),
            PythonRequirementTarget(
                {
                    "requirements": [
                        PipRequirement.parse(
                            "cachetools[ring,mongo]==4.1.1;python_version ~= '3.5'"
                        )
                    ],
                    "dependencies": [":Pipfile.lock"],
                },
                Address("", target_name="cachetools"),
            ),
        ],
    )


def test_supply_python_requirements_file(rule_runner: RuleRunner) -> None:
    """This tests that we can supply our own `_python_requirements_file`."""
    assert_pipenv_requirements(
        rule_runner,
        dedent(
            """
            pipenv_requirements(
                source='custom/pipfile/Pipfile.lock',
                pipfile_target='//:custom_pipfile_target'
            )

            _target_generator_sources_helper(
                name='custom_pipfile_target',
                sources=['custom/pipfile/Pipfile.lock']
            )
            """
        ),
        {"default": {"ansicolors": {"version": ">=1.18.0"}}},
        expected_file_dep=TargetGeneratorSourcesHelperTarget(
            {"sources": ["custom/pipfile/Pipfile.lock"]},
            Address("", target_name="custom_pipfile_target"),
        ),
        expected_targets=[
            PythonRequirementTarget(
                {
                    "requirements": [PipRequirement.parse("ansicolors>=1.18.0")],
                    "dependencies": ["//:custom_pipfile_target"],
                },
                Address("", target_name="ansicolors"),
            ),
        ],
        pipfile_lock_relpath="custom/pipfile/Pipfile.lock",
    )
