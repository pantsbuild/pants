# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class InterpreterSelectionIntegrationTest(PantsRunIntegrationTest):
  testproject = 'testprojects/src/python/interpreter_selection'

  def test_conflict(self):
    binary_target = '{}:deliberately_conficting_compatibility'.format(self.testproject)
    pants_run = self._build_pex(binary_target)
    self.assert_failure(pants_run,
                        'Unexpected successful build of {binary}.'.format(binary=binary_target))

  def test_select_26(self):
    self._maybe_test_version('2.6')

  def test_select_27(self):
    self._maybe_test_version('2.7')

  def _maybe_test_version(self, version):
    if self.has_python_version(version):
      print('Found python {}. Testing interpreter selection against it.'.format(version))
      echo = self._echo_version(version)
      v = echo.split('.')  # E.g., 2.6.8 .
      self.assertTrue(len(v) > 2, 'Not a valid version string: {}'.format(v))
      self.assertEquals(version, '{}.{}'.format(v[0], v[1]))
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

  def _build_pex(self, binary_target, config=None):
    # Avoid some known-to-choke-on interpreters.
    command = ['binary',
               binary_target,
               '--python-setup-interpreter-constraints=CPython>=2.6,<3',
               '--python-setup-interpreter-constraints=CPython>=3.3']
    return self.run_pants(command=command, config=config)
