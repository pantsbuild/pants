# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from json import dumps
from textwrap import dedent
from typing import Iterable

from pkg_resources import Requirement

from pants.backend.python.pipenv_requirements import PipenvRequirements
from pants.backend.python.target_types import PythonRequirementLibrary, PythonRequirementsFile
from pants.base.specs import AddressSpecs, DescendantAddresses, FilesystemSpecs, Specs
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.addresses import Address
from pants.engine.target import Targets
from pants.testutil.engine_util import Params
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class PipenvRequirementsTest(TestBase):
    @classmethod
    def alias_groups(cls):
        return BuildFileAliases(
            context_aware_object_factories={"pipenv_requirements": PipenvRequirements},
        )

    @classmethod
    def target_types(cls):
        return [PythonRequirementLibrary, PythonRequirementsFile]

    def assert_pipenv_requirements(
        self,
        build_file_entry: str,
        pipfile_lock: dict,
        *,
        expected_file_dep: PythonRequirementsFile,
        expected_targets: Iterable[PythonRequirementLibrary],
        pipfile_lock_relpath: str = "Pipfile.lock",
    ) -> None:
        self.add_to_build_file("", f"{build_file_entry}\n")
        self.create_file(pipfile_lock_relpath, dumps(pipfile_lock))
        targets = self.request_single_product(
            Targets,
            Params(
                Specs(AddressSpecs([DescendantAddresses("")]), FilesystemSpecs([])),
                create_options_bootstrapper(),
            ),
        )

        assert {expected_file_dep, *expected_targets} == set(targets)

    def test_pipfile_lock(self) -> None:
        """This tests that we correctly create a new python_requirement_library for each entry in a
        Pipfile.lock file.

        Edge cases:
        * Develop and Default requirements are used
        * If a module_mapping is given, and the project is in the map, we copy over a subset of the mapping to the created target.
        """

        self.assert_pipenv_requirements(
            "pipenv_requirements(module_mapping={'ansicolors': ['colors']})",
            {
                "default": {"ansicolors": {"version": ">=1.18.0"},},
                "develop": {
                    "cachetools": {"markers": "python_version ~= '3.5'", "version": "==4.1.1"},
                },
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

    def test_supply_python_requirements_file(self) -> None:
        """This tests that we can supply our own `_python_requirements_file`."""

        self.assert_pipenv_requirements(
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
            {"default": {"ansicolors": {"version": ">=1.18.0"},},},
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
