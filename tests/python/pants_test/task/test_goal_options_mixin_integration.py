# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class TestGoalOptionsMixinIntegration(PantsRunIntegrationTest):
  @classmethod
  def hermetic(cls):
    return True

  def _do_test_goal_options(self, flags, expected_one, expected_two):
    config = {
      'GLOBAL': {
        'pythonpath': '+["%(buildroot)s/tests/python"]',
        'backend_packages': '+["pants_test.task.echo_plugin"]'
      }
    }
    with self.pants_results(['echo'] + flags, config=config) as pants_run:
      self.assert_success(pants_run)
      def get_echo(which):
        with open(os.path.join(pants_run.workdir, 'echo', which, 'output')) as fp:
          return fp.read()
      self.assertEqual(expected_one, get_echo('one'))
      self.assertEqual(expected_two, get_echo('two'))

  def test_defaults(self):
    self._do_test_goal_options([], '0', '0')

  def test_set_at_goal_level(self):
    self._do_test_goal_options(['--enable'], '1', '2')

  def test_set_at_task_level(self):
    self._do_test_goal_options(['--echo-one-enable'], '1', '0')

  def test_set_at_goal_and_task_level(self):
    self._do_test_goal_options(['--enable', '--no-echo-one-enable'], '0', '2')
