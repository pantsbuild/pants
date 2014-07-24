# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import subprocess

import pytest

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class InterpreterSelectionIntegrationTest(PantsRunIntegrationTest):

  def test_conflict(self):
    pants_run = self._build_pex('tests/python/pants_test/python:'
                                'deliberately_conficting_compatibility')
    self.assertNotEqual(0, pants_run.returncode)

  def test_select_26(self):
    self._maybe_test_version('2.6')

  def test_select_27(self):
    self._maybe_test_version('2.7')

  def _maybe_test_version(self, version):
    if self.has_python_version(version):
      print('Found python %s. Testing interpreter selection against it.' % version)
      echo = self._echo_version(version)
      v = echo.split('.')  # E.g., 2.6.8 .
      self.assertTrue(len(v) > 2, 'Not a valid version string: %s' % v)
      self.assertEquals(version, '%s.%s' % (v[0], v[1]))
    else:
      print('No python %s found. Skipping.' % version)
      pytest.skip('No python %s on system' % version)

  def _echo_version(self, version):
    with temporary_dir() as distdir:
      config = {
        'DEFAULT': {
          'pants_distdir': distdir
        }
      }
      binary_name = 'echo_interpreter_version_%s' % version
      binary_target = 'tests/python/pants_test/python:' + binary_name
      pants_run = self._build_pex(binary_target, config)
      self.assertEqual(0, pants_run.returncode)
      # Run the built pex.
      exe = os.path.join(distdir, binary_name + '.pex')
      proc = subprocess.Popen([exe], stdout=subprocess.PIPE)
      (stdout_data, _) = proc.communicate()
      return stdout_data

  def _build_pex(self, binary_target, config=None):
    # Avoid some known-to-choke-on interpreters.
    command = ['goal', 'binary', binary_target,
               '--interpreter=CPython>=2.6,<3',
               '--interpreter=CPython>=3.3']
    return self.run_pants(command=command, config=config)


