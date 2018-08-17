# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.register import build_file_aliases
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.base.build_environment import pants_version
from pants_test.test_base import TestBase


class PantsRequirementTest(TestBase):
  @classmethod
  def alias_groups(cls):
    # NB: We use aliases and BUILD files to test proper registration of the pants_requirement macro.
    return build_file_aliases()

  def assert_pants_requirement(self, python_requirement_library):
    self.assertIsInstance(python_requirement_library, PythonRequirementLibrary)
    expected = PythonRequirement('pantsbuild.pants=={}'.format(pants_version()))

    def key(python_requirement):
      return (python_requirement.requirement.key,
              python_requirement.requirement.specs,
              python_requirement.requirement.extras)

    self.assertEqual([key(expected)],
                     [key(pr) for pr in python_requirement_library.payload.requirements])

    req = list(python_requirement_library.payload.requirements)[0]
    self.assertIsNotNone(req.requirement.marker)
    self.assertTrue(req.requirement.marker.evaluate(),
                    'pants_requirement() should always work in the current test environment')
    self.assertFalse(req.requirement.marker.evaluate({'python_version': '3.5'}))
    self.assertFalse(req.requirement.marker.evaluate({'python_version': '2.6'}))
    self.assertTrue(req.requirement.marker.evaluate({'python_version': '2.7'}))

  def test_default_name(self):
    self.add_to_build_file('3rdparty/python/pants', 'pants_requirement()')

    python_requirement_library = self.target('3rdparty/python/pants')
    self.assert_pants_requirement(python_requirement_library)

  def test_custom_name(self):
    self.add_to_build_file('3rdparty/python/pants', "pants_requirement('pantsbuild.pants')")

    python_requirement_library = self.target('3rdparty/python/pants:pantsbuild.pants')
    self.assert_pants_requirement(python_requirement_library)
