# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from contextlib import contextmanager
from pants.util.dirutil import safe_file_dump, safe_rmtree
from pants_test.pants_run_integration_test import PantsRunIntegrationTest, ensure_engine

SUBPROJ_SPEC = 'testprojects/src/python/subproject_test/'
SUBPROJ_ROOT = 'testprojects/src/python/subproject_test/subproject'

TEST_BUILD = 'testprojects/src/python/subproject_test/BUILD'
SUBPROJ_BUILD = 'testprojects/src/python/subproject_test/subproject/src/python/BUILD'
HELPERSHELPERS_BUILD = 'testprojects/src/python/subproject_test/subproject/src/python/helpershelpers/BUILD'

SUBPROJECT_TEST_CONTENTS = """
python_library (
  dependencies = ['//testprojects/src/python/subproject_test/subproject/src/python:helpers'],
)
"""

SUBPROJECT_TEST_SUBPROJECT_CONTENTS = """
python_library (
  name = 'helpers',
  dependencies = ['//src/python/helpershelpers'],
)
"""

SUBPROJECT_TEST_SUBPROJECT_HELPERSHELPERS_CONTENTS = """
python_library (
  name = 'helpershelpers',
)
"""

"""
Test layout
-----------

testprojects/
  src/
    python/
      subproject_test/
        BUILD
        subproject/
          src/
            python/
              BUILD/
              helpershelpers/
                BUILD/
"""


@contextmanager
def harness():
  try:
    safe_file_dump(TEST_BUILD, SUBPROJECT_TEST_CONTENTS)
    safe_file_dump(SUBPROJ_BUILD, SUBPROJECT_TEST_SUBPROJECT_CONTENTS)
    safe_file_dump(HELPERSHELPERS_BUILD, SUBPROJECT_TEST_SUBPROJECT_HELPERSHELPERS_CONTENTS)
    yield
  finally:
    safe_rmtree(SUBPROJ_SPEC)


class SubprojectIntegrationTest(PantsRunIntegrationTest):

  @ensure_engine
  def test_subproject_without_flag(self):
    """
    Assert that when getting the dependencies of a project which relies
    on a subproject which relies on its own internal library, a failure
    occurs without the --subproject-roots option
    """
    with harness():
      pants_args = ['dependencies', SUBPROJ_SPEC]
      pants_run = self.run_pants(pants_args)
      self.assert_failure(pants_run)

  @ensure_engine
  def test_subproject_with_flag(self):
    """
    Assert that when getting the dependencies of a project which relies on
    a subproject which relies on its own internal library, all things
    go well when that subproject is declared as a subproject
    """
    with harness():
      pants_args = ['--subproject-roots={}'.format(SUBPROJ_ROOT), 
                    'dependencies', SUBPROJ_SPEC]
      pants_run = self.run_pants(pants_args)
      self.assert_success(pants_run)
