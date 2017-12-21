# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.build_environment import get_buildroot
from pants.util.process_handler import subprocess
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PythonDistributionIntegrationTest(PantsRunIntegrationTest):
  # The paths to both a project containing a simple C extension (to be packaged into a
  # whl by setup.py) and an associated test to be consumed by the pants goals tested below.
  superhello_project = 'examples/src/python/example/python_distribution/hello/superhello'
  superhello_tests = 'examples/tests/python/example/python_distribution/hello/test_superhello'

  def test_pants_binary(self):
    self._maybe_test_pants_binary('2.7')

  def test_pants_run(self):
    self._maybe_test_pants_binary('2.7')

  def test_pants_test(self):
    self._maybe_test_pants_test('2.7')

  def test_python_distribution_integration_with_conflicting_deps(self):
    self._maybe_test_with_conflicting_deps('2.7')

  def _maybe_test_pants_binary(self, version):
    if self.has_python_version(version):
      print('Found python {}. Testing running on it.'.format(version))
      command=['binary', '{}:main'.format(self.superhello_project)]
      pants_run_27 = self.run_pants(command=command)
      self.assert_success(pants_run_27)
      # Check that the pex was built.
      pex = os.path.join(get_buildroot(), 'dist', 'main.pex')
      self.assertTrue(os.path.isfile(pex))
      # Check that the pex runs.
      output = subprocess.check_output(pex)
      self.assertIn('Super hello', output)
    else:
      print('No python {} found. Skipping.'.format(version))
      self.skipTest('No python {} on system'.format(version))

  def _maybe_test_pants_run(self, version):
    if self.has_python_version(version):
      print('Found python {}. Testing running on it.'.format(version))
      command=['run', '{}:main'.format(self.superhello_project)]
      pants_run_27 = self.run_pants(command=command)
      self.assert_success(pants_run_27)
      # Check that text was properly printed to stdout.
      self.assertIn('Super hello', pants_run_27.stdout_data)
    else:
      print('No python {} found. Skipping.'.format(version))
      self.skipTest('No python {} on system'.format(version))

  def _maybe_test_pants_test(self, version):
    if self.has_python_version(version):
      print('Found python {}. Testing running on it.'.format(version))
      command=['test', '{}:superhello'.format(self.superhello_tests)]
      pants_run_27 = self.run_pants(command=command)
      self.assert_success(pants_run_27)
    else:
      print('No python {} found. Skipping.'.format(version))
      self.skipTest('No python {} on system'.format(version))

  def _maybe_test_with_conflicting_deps(self, version):
    if self.has_python_version(version):
      # Test pants run. 
      command=['run', '{}:main_with_conflicting_dep'.format(self.superhello_project)]
      pants_run_27 = self.run_pants(command=command)
      self.assert_failure(pants_run_27)
      self.assertIn('Exception message: Could not satisfy all requirements', pants_run_27.stderr_data)
      # Test pants binary.
      command=['binary', '{}:main_with_conflicting_dep'.format(self.superhello_project)]
      pants_run_27 = self.run_pants(command=command)
      self.assert_failure(pants_run_27)
      self.assertIn('Exception message: Could not satisfy all requirements', pants_run_27.stderr_data)
    else:
      print('No python {} found. Skipping.'.format(version))
      self.skipTest('No python {} on system'.format(version))
