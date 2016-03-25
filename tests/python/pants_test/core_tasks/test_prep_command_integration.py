# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.util.dirutil import safe_delete
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PrepCommandIntegration(PantsRunIntegrationTest):

  SENTINELS = {
    'test' : '/tmp/running-prep-in-goal-test.txt',
    'compile' : '/tmp/running-prep-in-goal-compile.txt',
    'binary' : '/tmp/running-prep-in-goal-binary.txt'
  }

  def setUp(self):
    for path in self.SENTINELS.values():
      safe_delete(path)

  def assert_goal_ran(self, goal):
    self.assertTrue(os.path.exists(self.SENTINELS[goal]))

  def assert_goal_did_not_run(self, goal):
    self.assertFalse(os.path.exists(self.SENTINELS[goal]))

  def test_prep_command_in_compile(self):
    pants_run = self.run_pants([
      'compile',
      'testprojects/src/java/org/pantsbuild/testproject/prepcommand::'])
    self.assert_success(pants_run)

    self.assert_goal_ran('compile')
    self.assert_goal_did_not_run('test')
    self.assert_goal_did_not_run('binary')

  def test_prep_command_in_test(self):
    pants_run = self.run_pants([
      'test',
      'testprojects/src/java/org/pantsbuild/testproject/prepcommand::'])
    self.assert_success(pants_run)

    self.assert_goal_ran('compile')
    self.assert_goal_ran('test')
    self.assert_goal_did_not_run('binary')

  def test_prep_command_in_binary(self):
    pants_run = self.run_pants([
      'binary',
      'testprojects/src/java/org/pantsbuild/testproject/prepcommand::'])
    self.assert_success(pants_run)

    self.assert_goal_ran('compile')
    self.assert_goal_ran('binary')
    self.assert_goal_did_not_run('test')
