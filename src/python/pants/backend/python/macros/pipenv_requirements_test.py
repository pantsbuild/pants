# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from json import dumps
from textwrap import dedent
from typing import Iterable

import pytest
from pkg_resources import Requirement

from pants.backend.python.macros.pipenv_requirements import PipenvRequirements
from pants.backend.python.target_types import PythonRequirementLibrary, PythonRequirementsFile
from pants.base.specs import AddressSpecs, DescendantAddresses, FilesystemSpecs, Specs
from pants.engine.addresses import Address
from pants.engine.rules import QueryRule
from pants.engine.target import Targets
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[QueryRule(Targets, (OptionsBootstrapper, Specs))],
        target_types=[PythonRequirementLibrary, PythonRequirementsFile],
        context_aware_object_factories={"pipenv_requirements": PipenvRequirements},
    )


def assert_pipenv_requirements(
    rule_runner: RuleRunner,
    build_file_entry: str,
    pipfile_lock: dict,
    *,
    expected_file_dep: PythonRequirementsFile,
    expected_targets: Iterable[PythonRequirementLibrary],
    pipfile_lock_relpath: str = "Pipfile.lock",
) -> None:
    rule_runner.add_to_build_file("", f"{build_file_entry}\n")
    rule_runner.create_file(pipfile_lock_relpath, dumps(pipfile_lock))
    targets = rule_runner.request(
        Targets,
        [
            Specs(AddressSpecs([DescendantAddresses("")]), FilesystemSpecs([])),
            create_options_bootstrapper(),
        ],
    )

    assert {expected_file_dep, *expected_targets} == set(targets)


def test_pipfile_lock(rule_runner: RuleRunner) -> None:
    """This tests that we correctly create a new python_requirement_library for each entry in a
    Pipfile.lock file.

    Edge cases:
    * Develop and Default requirements are used
    * If a module_mapping is given, and the project is in the map, we copy over a subset of the
        mapping to the created target.
    """
    assert_pipenv_requirements(
        rule_runner,
        "pipenv_requirements(module_mapping={'ansicolors': ['colors']})",
        {
            "default": {"ansicolors": {"version": ">=1.18.0"}},
            "develop": {"cachetools": {"markers": "python_version ~= '3.5'", "version": "==4.1.1"}},
        },
        expected_file_dep=PythonRequirementsFile(
            {"sources": ["Pipfile.lock"]}, address=Address("", target_name="Pipfile.lock")
        ),
        expected_targets=[
            PythonRequirementLibrary(
                {
                    "requirements": [Requirement.parse("ansicolors>=1.18.0")],
                    "dependencies": [":Pipfile.lock"],
                    "module_mapping": {"ansicolors": ["colors"]},
                },
                address=Address("", target_name="ansicolors"),
            ),
            PythonRequirementLibrary(
                {
                    "requirements": [
                        Requirement.parse("cachetools==4.1.1;python_version ~= '3.5'")
                    ],
                    "dependencies": [":Pipfile.lock"],
                },
                address=Address("", target_name="cachetools"),
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
        expected_file_dep=PythonRequirementsFile(
            {"sources": ["Pipfile.lock"]}, address=Address("", target_name="Pipfile.lock")
        ),
        expected_targets=[
            PythonRequirementLibrary(
                {
                    "requirements": [Requirement.parse("ansicolors[neon]>=1.18.0")],
                    "dependencies": [":Pipfile.lock"],
                },
                address=Address("", target_name="ansicolors"),
            ),
            PythonRequirementLibrary(
                {
                    "requirements": [
                        Requirement.parse("cachetools[ring,mongo]==4.1.1;python_version ~= '3.5'")
                    ],
                    "dependencies": [":Pipfile.lock"],
                },
                address=Address("", target_name="cachetools"),
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
                requirements_relpath='custom/pipfile/Pipfile.lock',
                pipfile_target='//:custom_pipfile_target'
            )

            _python_requirements_file(
                name='custom_pipfile_target',
                sources=['custom/pipfile/Pipfile.lock']
            )
            """
        ),
        {"default": {"ansicolors": {"version": ">=1.18.0"}}},
        expected_file_dep=PythonRequirementsFile(
            {"sources": ["custom/pipfile/Pipfile.lock"]},
            address=Address("", target_name="custom_pipfile_target"),
        ),
        expected_targets=[
            PythonRequirementLibrary(
                {
                    "requirements": [Requirement.parse("ansicolors>=1.18.0")],
                    "dependencies": ["//:custom_pipfile_target"],
                },
                address=Address("", target_name="ansicolors"),
            ),
        ],
        pipfile_lock_relpath="custom/pipfile/Pipfile.lock",
    )
