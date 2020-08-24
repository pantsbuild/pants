# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import Iterable

import pytest
from pkg_resources import Requirement

from pants.backend.python.python_requirements import PythonRequirements
from pants.backend.python.target_types import PythonRequirementLibrary, PythonRequirementsFile
from pants.base.specs import AddressSpecs, DescendantAddresses, FilesystemSpecs, Specs
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import Targets
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class PantsRequirementTest(TestBase):
    @classmethod
    def alias_groups(cls):
        return BuildFileAliases(
            context_aware_object_factories={"python_requirements": PythonRequirements},
        )

    @classmethod
    def target_types(cls):
        return [PythonRequirementLibrary, PythonRequirementsFile]

    def assert_python_requirements(
        self,
        build_file_entry: str,
        requirements_txt: str,
        *,
        expected_file_dep: PythonRequirementsFile,
        expected_targets: Iterable[PythonRequirementLibrary],
        requirements_txt_relpath: str = "requirements.txt",
    ) -> None:
        self.add_to_build_file("", f"{build_file_entry}\n")
        self.create_file(requirements_txt_relpath, requirements_txt)
        targets = self.request_product(
            Targets,
            [
                Specs(AddressSpecs([DescendantAddresses("")]), FilesystemSpecs([])),
                create_options_bootstrapper(),
            ],
        )
        assert {expected_file_dep, *expected_targets} == set(targets)

    def test_requirements_txt(self) -> None:
        """This tests that we correctly create a new python_requirement_library for each entry in a
        requirements.txt file.

        Some edge cases:
        * We ignore comments and options (values that start with `--`).
        * If a module_mapping is given, and the project is in the map, we copy over a subset of the
          mapping to the created target.
        * Projects get normalized thanks to Requirement.parse().
        """
        self.assert_python_requirements(
            "python_requirements(module_mapping={'ansicolors': ['colors']})",
            dedent(
                """\
                # Comment.
                --find-links=https://duckduckgo.com
                ansicolors>=1.18.0
                Django==3.2 ; python_version>'3'
                Un-Normalized-PROJECT  # Inline comment.
                """
            ),
            expected_file_dep=PythonRequirementsFile(
                {"sources": ["requirements.txt"]},
                address=Address("", target_name="requirements.txt"),
            ),
            expected_targets=[
                PythonRequirementLibrary(
                    {
                        "dependencies": [":requirements.txt"],
                        "requirements": [Requirement.parse("ansicolors>=1.18.0")],
                        "module_mapping": {"ansicolors": ["colors"]},
                    },
                    address=Address("", target_name="ansicolors"),
                ),
                PythonRequirementLibrary(
                    {
                        "dependencies": [":requirements.txt"],
                        "requirements": [Requirement.parse("Django==3.2 ; python_version>'3'")],
                    },
                    address=Address("", target_name="Django"),
                ),
                PythonRequirementLibrary(
                    {
                        "dependencies": [":requirements.txt"],
                        "requirements": [Requirement.parse("Un_Normalized_PROJECT")],
                    },
                    address=Address("", target_name="Un-Normalized-PROJECT"),
                ),
            ],
        )

    def test_invalid_req(self) -> None:
        """Test that we give a nice error message."""
        with pytest.raises(ExecutionError) as exc:
            self.assert_python_requirements(
                "python_requirements()",
                "\n\nNot A Valid Req == 3.7",
                expected_file_dep=PythonRequirementsFile({}, address=Address("doesnt_matter")),
                expected_targets=[],
            )
        assert (
            "Invalid requirement in requirements.txt at line 3 due to value 'Not A Valid Req == "
            "3.7'."
        ) in str(exc.value)

    def test_relpath_override(self) -> None:
        self.assert_python_requirements(
            "python_requirements(requirements_relpath='subdir/requirements.txt')",
            "ansicolors>=1.18.0",
            requirements_txt_relpath="subdir/requirements.txt",
            expected_file_dep=PythonRequirementsFile(
                {"sources": ["subdir/requirements.txt"]},
                address=Address("", target_name="subdir/requirements.txt"),
            ),
            expected_targets=[
                PythonRequirementLibrary(
                    {
                        "dependencies": [":subdir/requirements.txt"],
                        "requirements": [Requirement.parse("ansicolors>=1.18.0")],
                    },
                    address=Address("", target_name="ansicolors"),
                ),
            ],
        )
