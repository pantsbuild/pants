# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import Tuple

import pytest

from pants.backend.python.target_types import PythonRequirementLibrary, PythonRequirementsField
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import WrappedTarget
from pants.python.python_requirement import PythonRequirement
from pants.testutil.test_base import TestBase


class PythonRequirementListTest(TestBase):
    @classmethod
    def alias_groups(cls):
        return BuildFileAliases(objects={"python_requirement": PythonRequirement})

    @classmethod
    def target_types(cls):
        return [PythonRequirementLibrary]

    def get_python_requirements(
        self, build_file_entry: str, *, target_name: str
    ) -> Tuple[PythonRequirement, ...]:
        self.add_to_build_file("lib", f"{build_file_entry}\n")
        target = self.request_single_product(WrappedTarget, Address("lib", target_name)).target
        assert isinstance(target, PythonRequirementLibrary)
        return target[PythonRequirementsField].value

    def test_bad_list(self) -> None:
        build_file = dedent(
            """
            python_requirement_library(
              name='pyunit',
              requirements=[
                'argparse==1.2.1'
              ]
            )
            """
        )
        with pytest.raises(ExecutionError):
            self.get_python_requirements(build_file, target_name="pyunit")

    def test_good_list(self) -> None:
        build_file = dedent(
            """
            python_requirement_library(
              name='pyunit',
              requirements=[
                 python_requirement('argparse==1.2.1'),
                 python_requirement('ansicolors>=1.18'),
              ]
            )
            """
        )
        requirements = self.get_python_requirements(build_file, target_name="pyunit")
        assert len(requirements) == 2
        assert [req.requirement for req in requirements] == [
            PythonRequirement("argparse==1.2.1").requirement,
            PythonRequirement("ansicolors>=1.18").requirement,
        ]
