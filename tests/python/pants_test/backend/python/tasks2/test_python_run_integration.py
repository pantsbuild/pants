# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PythonRunIntegrationTest(PantsRunIntegrationTest):
  testproject = 'testprojects/src/python/interpreter_selection'

  def test_run_3(self):
    self._maybe_run_version('3')

  def test_run_27(self):
    self._maybe_run_version('2.7')

  def test_run_27_and_then_3(self):
    with temporary_dir() as interpreters_cache:
      pants_ini_config = {'python-setup': {'interpreter_cache_dir': interpreters_cache}}
      pants_run_27 = self.run_pants(
        command=['run', '{}:echo_interpreter_version_2.7'.format(self.testproject)],
        config=pants_ini_config
      )
      self.assert_success(pants_run_27)
      pants_run_3 = self.run_pants(
        command=['run', '{}:echo_interpreter_version_3'.format(self.testproject),
                 '--python-setup-interpreter-constraints=CPython>=2.7,<3',
                 '--python-setup-interpreter-constraints=CPython>=3.3'],
        config=pants_ini_config
      )
      self.assert_success(pants_run_3)

  def test_die(self):
    command = ['run',
               '{}:die'.format(self.testproject),
               '--python-setup-interpreter-constraints=CPython>=2.7,<3',
               '--python-setup-interpreter-constraints=CPython>=3.3',
               '--quiet']
    pants_run = self.run_pants(command=command)
    assert pants_run.returncode == 57

  def test_get_env_var(self):
    var_key = 'SOME_MAGICAL_VAR'
    var_val = 'a value'
    command = ['-q',
               'run',
               'testprojects/src/python/print_env',
               '--',
               var_key]
    pants_run = self.run_pants(command=command, extra_env={var_key: var_val})
    self.assert_success(pants_run)
    self.assertEquals(var_val, pants_run.stdout_data.strip())

  def _maybe_run_version(self, version):
    if self.has_python_version(version):
      print('Found python {}. Testing running on it.'.format(version))
      echo = self._run_echo_version(version)
      v = echo.split('.')  # E.g., 2.7.13.
      self.assertTrue(len(v) > 2, 'Not a valid version string: {}'.format(v))
      expected_components = version.split('.')
      self.assertEquals(expected_components, v[:len(expected_components,)])
    else:
      print('No python {} found. Skipping.'.format(version))
      self.skipTest('No python {} on system'.format(version))

  def _run_echo_version(self, version):
    binary_name = 'echo_interpreter_version_{}'.format(version)
    binary_target = '{}:{}'.format(self.testproject, binary_name)
    # Build a pex.
    # Avoid some known-to-choke-on interpreters.
    command = ['run',
               binary_target,
               '--python-setup-interpreter-constraints=CPython>=2.7,<3',
               '--python-setup-interpreter-constraints=CPython>=3.3',
               '--quiet']
    pants_run = self.run_pants(command=command)
    return pants_run.stdout_data.rstrip().split('\n')[-1]
