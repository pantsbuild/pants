# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.util.contextutil import temporary_dir
from pants.util.process_handler import subprocess
from pants_test.backend.python.interpreter_selection_utils import (PY_3, PY_27, skip_unless_python3,
                                                                   skip_unless_python27)
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class InterpreterSelectionIntegrationTest(PantsRunIntegrationTest):
  testproject = 'testprojects/src/python/interpreter_selection'

  def test_cli_option_wins_compatibility_conflict(self):
    # Tests that targets with compatibility conflicts collide.
    binary_target = '{}:deliberately_conficting_compatibility'.format(self.testproject)
    pants_run = self._build_pex(binary_target)
    self.assert_success(pants_run, 'Failed to build {binary}.'.format(binary=binary_target))

  def test_conflict_via_config(self):
    # Tests that targets with compatibility conflict with targets with default compatibility.
    # NB: Passes empty `args` to avoid having the default CLI args override the config.
    config = {
        'python-setup': {
          'interpreter_constraints': ['CPython<2.7'],
        }
      }
    binary_target = '{}:echo_interpreter_version'.format(self.testproject)
    pants_run = self._build_pex(binary_target, config=config, args=[])
    self.assert_failure(pants_run,
                        'Unexpected successful build of {binary}.'.format(binary=binary_target))
    self.assertIn('Unable to detect a suitable interpreter for compatibilities',
                  pants_run.stdout_data)

  @skip_unless_python3
  def test_select_3(self):
    self._test_version(PY_3)

  @skip_unless_python27
  def test_select_27(self):
    self._test_version(PY_27)

  def _test_version(self, version):
    echo = self._echo_version(version)
    v = echo.split('.')  # E.g., 2.7.13.
    self.assertTrue(len(v) > 2, 'Not a valid version string: {}'.format(v))
    expected_components = version.split('.')
    self.assertEqual(expected_components, v[:len(expected_components)])

  def _echo_version(self, version):
    with temporary_dir() as distdir:
      config = {
        'GLOBAL': {
          'pants_distdir': distdir
        }
      }
      binary_name = 'echo_interpreter_version_{}'.format(version)
      binary_target = '{}:{}'.format(self.testproject, binary_name)
      pants_run = self._build_pex(binary_target, config, version=version)
      self.assert_success(pants_run, 'Failed to build {binary}.'.format(binary=binary_target))

      # Run the built pex.
      exe = os.path.join(distdir, binary_name + '.pex')
      proc = subprocess.Popen([exe], stdout=subprocess.PIPE)
      (stdout_data, _) = proc.communicate()
      return stdout_data.decode('utf-8')

  def _build_pex(self, binary_target, config=None, args=None, version=PY_27):
    # By default, Avoid some known-to-choke-on interpreters.
    if version == PY_3:
      constraint = '["CPython>=3.4,<4"]'
    else:
      constraint = '["CPython>=2.7,<3"]'
    args = list(args) if args is not None else [
          '--python-setup-interpreter-constraints={}'.format(constraint)
        ]
    command = ['binary', binary_target] + args
    return self.run_pants(command=command, config=config)
