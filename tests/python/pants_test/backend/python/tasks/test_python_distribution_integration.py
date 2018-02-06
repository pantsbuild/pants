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
  fasthello_project = 'examples/src/python/example/python_distribution/hello/fasthello'
  fasthello_tests = 'examples/tests/python/example/python_distribution/hello/test_fasthello'
  fasthello_install_requires = 'testprojects/src/python/python_distribution/fasthello_with_install_requires'

  def test_pants_binary(self):
    command=['binary', '{}:main'.format(self.fasthello_project)]
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)
    # Check that the pex was built.
    pex = os.path.join(get_buildroot(), 'dist', 'main.pex')
    self.assertTrue(os.path.isfile(pex))
    # Check that the pex runs.
    output = subprocess.check_output(pex)
    self.assertIn('Super hello', output)
    # Cleanup
    os.remove(pex)

  def test_pants_run(self):
    command=['run', '{}:main'.format(self.fasthello_project)]
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)
    # Check that text was properly printed to stdout.
    self.assertIn('Super hello', pants_run.stdout_data)

  def test_pants_test(self):
    command=['test', '{}:fasthello'.format(self.fasthello_tests)]
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)

  def test_with_install_requires(self):
    command=['run', '{}:main_with_no_conflict'.format(self.fasthello_install_requires)]
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)
    self.assertIn('United States', pants_run.stdout_data)
    command=['binary', '{}:main_with_no_conflict'.format(self.fasthello_install_requires)]
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)
    pex = os.path.join(get_buildroot(), 'dist', 'main_with_no_conflict.pex')
    output = subprocess.check_output(pex)
    self.assertIn('United States', output)
    os.remove(pex)

  def test_with_conflicting_transitive_deps(self):
    command=['run', '{}:main_with_conflicting_dep'.format(self.fasthello_install_requires)]
    pants_run = self.run_pants(command=command)
    self.assert_failure(pants_run)
    self.assertIn('pycountry', pants_run.stderr_data)
    self.assertIn('fasthello', pants_run.stderr_data)
    command=['binary', '{}:main_with_conflicting_dep'.format(self.fasthello_install_requires)]
    pants_run = self.run_pants(command=command)
    self.assert_failure(pants_run)
    self.assertIn('pycountry', pants_run.stderr_data)
    self.assertIn('fasthello', pants_run.stderr_data)

  def test_pants_binary_dep_isolation_with_multiple_targets(self):
    command=['binary', '{}:main_with_no_conflict'.format(self.fasthello_install_requires),
             '{}:main_with_no_pycountry'.format(self.fasthello_install_requires)]
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)
    # Check that the pex was built.
    pex1 = os.path.join(get_buildroot(), 'dist', 'main_with_no_conflict.pex')
    self.assertTrue(os.path.isfile(pex1))
    pex2 = os.path.join(get_buildroot(), 'dist', 'main_with_no_pycountry.pex')
    self.assertTrue(os.path.isfile(pex2))
    # Check that the pex 1 runs.
    output = subprocess.check_output(pex1)
    self.assertIn('Super hello', output)
    # Check that the pex 2 fails due to no python_dists leaked into it.
    try:
      output = subprocess.check_output(pex2)
    except subprocess.CalledProcessError as e:
      self.assertNotEquals(0, e.returncode)
    # Cleanup
    os.remove(pex1)
    os.remove(pex2)
