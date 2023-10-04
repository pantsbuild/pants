# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from json import dumps

import pytest

from pants.backend.python.goals import lockfile
from pants.backend.python.macros import pipenv_requirements
from pants.backend.python.macros.pipenv_requirements import PipenvRequirementsTargetGenerator
from pants.backend.python.target_types import PythonRequirementTarget
from pants.core.target_types import TargetGeneratorSourcesHelperTarget
from pants.engine.addresses import Address
from pants.engine.internals.graph import _TargetParametrizations, _TargetParametrizationsRequest
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=(
            *lockfile.rules(),
            *pipenv_requirements.rules(),
            QueryRule(_TargetParametrizations, [_TargetParametrizationsRequest]),
        ),
        target_types=[PipenvRequirementsTargetGenerator],
    )


def assert_pipenv_requirements(
    rule_runner: RuleRunner,
    build_file_entry: str,
    pipfile_lock: dict,
    *,
    expected_targets: set[Target],
) -> None:
    rule_runner.write_files({"BUILD": build_file_entry, "Pipfile.lock": dumps(pipfile_lock)})
    result = rule_runner.request(
        _TargetParametrizations,
        [
            _TargetParametrizationsRequest(
                Address("", target_name="reqs"), description_of_origin="tests"
            )
        ],
    )
    assert set(result.parametrizations.values()) == expected_targets


def test_pipfile_lock(rule_runner: RuleRunner) -> None:
    """This tests that we correctly create a new python_requirement for each entry in a Pipfile.lock
    file.

    Edge cases:

    * Develop and Default requirements are used
    * module_mapping works.
    """
    file_addr = Address("", target_name="reqs", relative_file_path="Pipfile.lock")
    assert_pipenv_requirements(
        rule_runner,
        "pipenv_requirements(name='reqs', module_mapping={'ansicolors': ['colors']})",
        {
            "default": {"ansicolors": {"version": ">=1.18.0"}},
            "develop": {
                "cachetools": {
                    "markers": "python_version ~= '3.5'",
                    "version": "==4.1.1",
                    "extras": ["ring", "mongo"],
                }
            },
        },
        expected_targets={
            PythonRequirementTarget(
                {
                    "requirements": ["ansicolors>=1.18.0"],
                    "modules": ["colors"],
                    "dependencies": [file_addr.spec],
                },
                Address("", target_name="reqs", generated_name="ansicolors"),
            ),
            PythonRequirementTarget(
                {
                    "requirements": ["cachetools[ring, mongo]==4.1.1;python_version ~= '3.5'"],
                    "dependencies": [file_addr.spec],
                },
                Address("", target_name="reqs", generated_name="cachetools"),
            ),
            TargetGeneratorSourcesHelperTarget({"source": "Pipfile.lock"}, file_addr),
        },
    )


def test_pipfile_lockfile_dependency(rule_runner: RuleRunner) -> None:
    """This tests that we adds a dependency on the lockfile for the resolve for each generated
    python_requirement."""
    rule_runner.set_options(["--python-enable-resolves"])
    file_addr = Address("", target_name="reqs", relative_file_path="Pipfile.lock")
    lock_addr = Address(
        "3rdparty/python", target_name="_python-default_lockfile", relative_file_path="default.lock"
    )
    assert_pipenv_requirements(
        rule_runner,
        "pipenv_requirements(name='reqs', module_mapping={'ansicolors': ['colors']})",
        {
            "default": {"ansicolors": {"version": ">=1.18.0"}},
            "develop": {
                "cachetools": {
                    "markers": "python_version ~= '3.5'",
                    "version": "==4.1.1",
                    "extras": ["ring", "mongo"],
                }
            },
        },
        expected_targets={
            PythonRequirementTarget(
                {
                    "requirements": ["ansicolors>=1.18.0"],
                    "modules": ["colors"],
                    "dependencies": [file_addr.spec, lock_addr.spec],
                },
                Address("", target_name="reqs", generated_name="ansicolors"),
            ),
            PythonRequirementTarget(
                {
                    "requirements": ["cachetools[ring, mongo]==4.1.1;python_version ~= '3.5'"],
                    "dependencies": [file_addr.spec, lock_addr.spec],
                },
                Address("", target_name="reqs", generated_name="cachetools"),
            ),
            TargetGeneratorSourcesHelperTarget({"source": file_addr.filename}, file_addr),
        },
    )
