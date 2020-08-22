# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from json import dumps
from typing import Iterable

from pkg_resources import Requirement

from pants.backend.python.pipenv_requirements import PipenvRequirements
from pants.backend.python.target_types import PythonRequirementLibrary, PythonRequirementsFile
from pants.base.specs import AddressSpecs, DescendantAddresses, FilesystemSpecs, Specs
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.addresses import Address
from pants.engine.target import Targets
from pants.python.python_requirement import PythonRequirement
from pants.testutil.engine.util import Params
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class PipenvRequirementsTest(TestBase):
    @classmethod
    def alias_groups(cls):
        return BuildFileAliases(
            objects={"python_requirement": PythonRequirement},
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
        * A library entry that specifies a repo url uses it.
        * A library entry that specifies a repo name matches against the _meta.sources object.
        * A library entry can specify a dict or string index.
        * If a module_mapping is given, and the project is in the map, we copy over a subset of the mapping to the created target.
        """

        self.assert_pipenv_requirements(
            "pipenv_requirements(module_mapping={'ansicolors': ['colors']})",
            {
                "_meta": {"sources": [{"name": "repo1", "url": "https://repo1.pypi.org"}]},
                "default": {
                    "ansicolors": {"version": ">=1.18.0"}
                    #     "cachetools": {
                    #         "markers": "python_version ~= '3.5'",
                    #         "version": "==4.1.1"
                    #         "index": "repo1"
                    #     },
                    # },
                    # "develop": {
                    #     "deprecated": {
                    #         "index": "https://repo2.pypi.org",
                    #         "version": "==1.2.10"
                    #     },
                    #     "edgegrid-python": {
                    #         "index": { "url": "https://repo3.pypi.org" },
                    #         "version": "==1.1.1"
                    #     },
                },
            },
            expected_file_dep=PythonRequirementsFile(
                {"sources": ["Pipfile.lock"]}, address=Address("", target_name="Pipfile.lock")
            ),
            expected_targets=[
                PythonRequirementLibrary(
                    {
                        "requirements": [
                            PythonRequirement(
                                Requirement.parse("ansicolors>=1.18.0"),
                                repository="https://repo1.pypi.org",
                                modules=["colors"],
                            )
                        ],
                        "dependencies": [":Pipfile.lock"],
                    },
                    address=Address("", target_name="ansicolors"),
                ),
                # PythonRequirementLibrary(
                #     {
                #         "dependencies": [":Pipfile.lock"],
                #         "requirements": [
                #             PythonRequirement(
                #                 Requirement.parse("cachetools>=1.18.0"),
                #                 repository="https://repo1.pypi.org"
                #                 modules=["colors"]
                #             )],
                #         "module_mapping":
                #     },
                #     address=Address("", target_name="ansicolors")
                # ),
            ],
        )
