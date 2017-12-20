# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import sys

from pex.pex_bootstrapper import get_pex_info

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.testutils.pexrc_util import setup_pexrc_with_pex_python_path


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

  def test_pants_run_interpreter_selection_with_pexrc(self):
    py27 = '2.7'
    py3 = '3'
    if self.has_python_version(py27) and self.has_python_version(py3):
      print('Found both python {} and python {}. Running test.'.format(py27, py3))
      py27_path, py3_path = self.python_interpreter_path(py27), self.python_interpreter_path(py3)
      with setup_pexrc_with_pex_python_path(os.path.join(os.path.dirname(sys.argv[0]), '.pexrc'), [py27_path, py3_path]):
        with temporary_dir() as interpreters_cache:
          pants_ini_config = {'python-setup': {'interpreter_cache_dir': interpreters_cache}}
          pants_run_27 = self.run_pants(
            command=['run', '{}:main_py2'.format(os.path.join(self.testproject, 'python_3_selection_testing'))],
            config=pants_ini_config
          )
          self.assert_success(pants_run_27)
          # Interpreter selection for Python 2 is problematic in CI due to multiple virtualenvs in play.
          if not os.getenv('CI'):
            self.assertIn(py27_path.split(py27)[0], pants_run_27.stdout_data)
          pants_run_3 = self.run_pants(
            command=['run', '{}:main_py3'.format(os.path.join(self.testproject, 'python_3_selection_testing'))],
            config=pants_ini_config
          )
          self.assert_success(pants_run_3)
          # Protection for when the sys.executable path underlies a symlink pointing to 'python' without '3'
          # at the end of the basename.
          self.assertIn(py3_path.split(py3)[0], pants_run_3.stdout_data)
    else:
      print('Could not find both python {} and python {} on system. Skipping.'.format(py27, py3))
      self.skipTest('Missing neccesary Python interpreters on system.')

  def test_pants_binary_interpreter_selection_with_pexrc(self):
    py27 = '2.7'
    py3 = '3'
    if self.has_python_version(py27) and self.has_python_version(py3):
      print('Found both python {} and python {}. Running test.'.format(py27, py3))
      py27_path, py3_path = self.python_interpreter_path(py27), self.python_interpreter_path(py3)
      with setup_pexrc_with_pex_python_path(os.path.join(os.path.dirname(sys.argv[0]), '.pexrc')  , [py27_path, py3_path]):
        with temporary_dir() as interpreters_cache:
          pants_ini_config = {'python-setup': {'interpreter_cache_dir': interpreters_cache}}
          pants_run_27 = self.run_pants(
            command=['binary', '{}:main_py2'.format(os.path.join(self.testproject, 'python_3_selection_testing'))],
            config=pants_ini_config
          )
          self.assert_success(pants_run_27)
          pants_run_3 = self.run_pants(
            command=['binary', '{}:main_py3'.format(os.path.join(self.testproject, 'python_3_selection_testing'))],
            config=pants_ini_config
          )
          self.assert_success(pants_run_3)
    else:
      print('Could not find both python {} and python {} on system. Skipping.'.format(py27, py3))
      self.skipTest('Missing neccesary Python interpreters on system.')

    # Ensure proper interpreter constraints were passed to built pexes.
    py2_pex = os.path.join(os.getcwd(), 'dist', 'main_py2.pex')
    py3_pex = os.path.join(os.getcwd(), 'dist', 'main_py3.pex')
    py2_info = get_pex_info(py2_pex)
    py3_info = get_pex_info(py3_pex)
    self.assertIn('CPython>2.7.6,<3', py2_info.interpreter_constraints)
    self.assertIn('CPython>3', py3_info.interpreter_constraints)

    # Cleanup created pexes.
    os.remove(py2_pex)
    os.remove(py3_pex)

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
