# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager
from textwrap import dedent

from pants.util.dirutil import safe_open
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PrepCommandIntegrationTest(PantsRunIntegrationTest):

  _SENTINELS = {
    'test': 'running-prep-in-goal-test.txt',
    'compile': 'running-prep-in-goal-compile.txt',
    'binary': 'running-prep-in-goal-binary.txt'
  }

  @classmethod
  def _emit_targets(cls, workdir):
    prep_command_path = os.path.join(workdir, 'src/java/org/pantsbuild/prepcommand')
    with safe_open(os.path.join(prep_command_path, 'BUILD'), 'w') as fp:
      for name, touch_target in cls._SENTINELS.items():
        fp.write(dedent("""
          prep_command(
            name='{name}',
            goal='{goal}',
            prep_executable='touch',
            prep_args=['{tmpdir}/{touch_target}'],
          )
        """.format(name=name, goal=name, tmpdir=workdir, touch_target=touch_target)))
    return ['{}:{}'.format(prep_command_path, name) for name in cls._SENTINELS]

  @classmethod
  def _goal_ran(cls, basedir, goal):
    return os.path.exists(os.path.join(basedir, cls._SENTINELS[goal]))

  def _assert_goal_ran(self, basedir, goal):
    self.assertTrue(self._goal_ran(basedir, goal))

  def _assert_goal_did_not_run(self, basedir, goal):
    self.assertFalse(self._goal_ran(basedir, goal))

  @contextmanager
  def _execute_pants(self, goal):
    with self.temporary_workdir() as workdir:
      prep_commands_specs = self._emit_targets(workdir)
      # Make sure the emitted BUILD under .pants.d is not ignored.
      config = {
        'GLOBAL': {
          'ignore_patterns': []
        }
      }
      pants_run = self.run_pants_with_workdir([goal] + prep_commands_specs, workdir, config=config)
      self.assert_success(pants_run)
      yield workdir

  def test_prep_command_in_compile(self):
    with self._execute_pants('compile') as workdir:
      self._assert_goal_ran(workdir, 'compile')
      self._assert_goal_did_not_run(workdir, 'test')
      self._assert_goal_did_not_run(workdir, 'binary')

  def test_prep_command_in_test(self):
    with self._execute_pants('test') as workdir:
      self._assert_goal_ran(workdir, 'compile')
      self._assert_goal_ran(workdir, 'test')
      self._assert_goal_did_not_run(workdir, 'binary')

  def test_prep_command_in_binary(self):
    with self._execute_pants('binary') as workdir:
      self._assert_goal_ran(workdir, 'compile')
      self._assert_goal_ran(workdir, 'binary')
      self._assert_goal_did_not_run(workdir, 'test')
