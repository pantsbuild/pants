# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import pytest

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PythonRunIntegrationTest(PantsRunIntegrationTest):

  def test_run_26(self):
    self._maybe_run_version('2.6')

  def test_run_27(self):
    self._maybe_run_version('2.7')

  def _maybe_run_version(self, version):
    if self.has_python_version(version):
      print('Found python %s. Testing running on it.' % version)
      echo = self._run_echo_version(version)
      v = echo.split('.')  # E.g., 2.6.8.
      self.assertTrue(len(v) > 2, 'Not a valid version string: %s' % v)
      self.assertEquals(version, '%s.%s' % (v[0], v[1]))
    else:
      print('No python %s found. Skipping.' % version)
      pytest.skip('No python %s on system' % version)

  def _run_echo_version(self, version):
    binary_name = 'echo_interpreter_version_%s' % version
    binary_target = 'tests/python/pants_test/python:' + binary_name
    # Build a pex.
    # Avoid some known-to-choke-on interpreters.
    command = ['goal', 'run', binary_target,
               '--interpreter=CPython>=2.6,<3',
               '--interpreter=CPython>=3.3', '--quiet']
    # Parsing the version out of the pants output will be fragile, but we assume
    # that the right thing happened if the exit code is 0.
    pants_run = self.run_pants(command=command)
    return pants_run.stdout_data.rstrip().split('\n')[-1]
