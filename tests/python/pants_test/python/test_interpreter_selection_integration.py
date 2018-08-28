# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.util.contextutil import temporary_dir
from pants.util.process_handler import subprocess
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

  def test_select_3(self):
    self._maybe_test_version('3')

  def test_select_27(self):
    self._maybe_test_version('2.7')

  def _maybe_test_version(self, version):
    if self.has_python_version(version):
      print('Found python {}. Testing interpreter selection against it.'.format(version))
      echo = self._echo_version(version)
      v = echo.split('.')  # E.g., 2.7.13.
      self.assertTrue(len(v) > 2, 'Not a valid version string: {}'.format(v))
      expected_components = version.split('.')
      self.assertEqual(expected_components, v[:len(expected_components)])
    else:
      print('No python {} found. Skipping.'.format(version))
      self.skipTest('No python {} on system'.format(version))

  def _echo_version(self, version):
    with temporary_dir() as distdir:
      config = {
        'GLOBAL': {
          'pants_distdir': distdir
        }
      }
      binary_name = 'echo_interpreter_version_{}'.format(version)
      binary_target = '{}:{}'.format(self.testproject, binary_name)
      pants_run = self._build_pex(binary_target, config)
      self.assert_success(pants_run, 'Failed to build {binary}.'.format(binary=binary_target))

      # Run the built pex.
      exe = os.path.join(distdir, binary_name + '.pex')
      proc = subprocess.Popen([exe], stdout=subprocess.PIPE)
      (stdout_data, _) = proc.communicate()
      return stdout_data

  def _build_pex(self, binary_target, config=None, args=None):
    # By default, Avoid some known-to-choke-on interpreters.
    args = list(args) if args is not None else [
          '--python-setup-interpreter-constraints=CPython>=2.7,<3',
          '--python-setup-interpreter-constraints=CPython>=3.3',
        ]
    command = ['binary', binary_target] + args
    return self.run_pants(command=command, config=config)
