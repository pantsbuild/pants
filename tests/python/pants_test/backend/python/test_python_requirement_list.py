# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.python.python_requirement import PythonRequirement
from pants.testutil.test_base import TestBase


class PythonRequirementListTest(TestBase):
    @classmethod
    def alias_groups(cls):
        return BuildFileAliases(
            targets={"python_requirement_library": PythonRequirementLibrary},
            objects={"python_requirement": PythonRequirement},
        )

    def test_bad_list(self):
        self.add_to_build_file(
            "lib",
            dedent(
                """
                python_requirement_library(
                  name='pyunit',
                  requirements=[
                    'argparse==1.2.1'
                  ]
                )
                """
            ),
        )
        with self.assertRaises(TargetDefinitionException):
            self.target("lib:pyunit")

    def test_good_list(self):
        self.add_to_build_file(
            "lib",
            dedent(
                """
                python_requirement_library(
                  name='pyunit',
                  requirements=[
                    python_requirement('argparse==1.2.1')
                  ]
                )
                """
            ),
        )

        self.target("lib:pyunit")
