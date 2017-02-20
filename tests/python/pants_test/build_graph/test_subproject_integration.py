# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, 
                        print_function, unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest

SUBPROJ_SPEC = 'testprojects/src/python/subproject_test/'
SUBPROJ_ROOT = 'testprojects/src/python/subproject_test/subproject'


class SubprojectIntegrationTest(PantsRunIntegrationTest):

  def test_subproject_without_flag(self):
    """
    Assert that when getting the dependendies of a project which relies
    on a subproject which relies on its own internal library, a failure
    occurs without the --subproject-roots option
    """
    pants_args = ['dependencies', SUBPROJ_SPEC]
    pants_run = self.run_pants(pants_args)
    self.assert_failure(pants_run)

  def test_subproject_with_flag(self):
    """
    Assert that when getting the dependencies of a project which relies on
    a subproject which relies on its own internal library, all things
    go well when that subproject is declared as a subproject
    """
    pants_args = ['--subproject-roots={}'.format(SUBPROJ_ROOT), 
                  'dependencies', SUBPROJ_SPEC]
    pants_run = self.run_pants(pants_args)
    self.assert_success(pants_run)
