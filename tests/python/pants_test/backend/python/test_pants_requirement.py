# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.register import build_file_aliases
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.base.build_environment import pants_version
from pants_test.base_test import BaseTest


class PantsRequirementTest(BaseTest):
  @property
  def alias_groups(self):
    # NB: We use aliases and BUILD files to test proper registration of the pants_requirement macro.
    return build_file_aliases()

  def assert_pants_requirement(self, python_requirement_library):
    self.assertIsInstance(python_requirement_library, PythonRequirementLibrary)
    pants_requirement = PythonRequirement('pantsbuild.pants=={}'.format(pants_version()))
    self.assertEqual([pants_requirement.requirement],
                     list(pr.requirement for pr in python_requirement_library.payload.requirements))

  def test_default_name(self):
    self.add_to_build_file('3rdparty/python/pants', 'pants_requirement()')

    python_requirement_library = self.target('3rdparty/python/pants')
    self.assert_pants_requirement(python_requirement_library)

  def test_custom_name(self):
    self.add_to_build_file('3rdparty/python/pants', "pants_requirement('pantsbuild.pants')")

    python_requirement_library = self.target('3rdparty/python/pants:pantsbuild.pants')
    self.assert_pants_requirement(python_requirement_library)
