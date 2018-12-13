# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import glob
import os
import re
from builtins import open

from pants.util.collections import assert_single_element
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import is_executable
from pants.util.process_handler import subprocess
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.testutils.py2_compat import assertRegex


class PythonDistributionIntegrationTest(PantsRunIntegrationTest):
  # The paths to both a project containing a simple C extension (to be packaged into a
  # whl by setup.py) and an associated test to be consumed by the pants goals tested below.
  fasthello_project = 'examples/src/python/example/python_distribution/hello/fasthello'
  fasthello_tests = 'examples/tests/python/example/python_distribution/hello/test_fasthello'
  fasthello_install_requires_dir = 'testprojects/src/python/python_distribution/fasthello_with_install_requires'
  hello_setup_requires = 'examples/src/python/example/python_distribution/hello/setup_requires'

  def _assert_native_greeting(self, output):
    self.assertIn('Hello from C!', output)
    self.assertIn('Hello from C++!', output)

  def test_pants_binary(self):
    with temporary_dir() as tmp_dir:
      pex = os.path.join(tmp_dir, 'main.pex')
      command=[
        '--pants-distdir={}'.format(tmp_dir), 'binary', '{}:main'.format(self.fasthello_project)]
      pants_run = self.run_pants(command=command)
      self.assert_success(pants_run)
      # Check that the pex was built.
      self.assertTrue(os.path.isfile(pex))
      # Check that the pex runs.
      output = subprocess.check_output(pex).decode('utf-8')
      self._assert_native_greeting(output)
      # Check that we have exactly one wheel output.
      single_wheel_output = assert_single_element(glob.glob(os.path.join(tmp_dir, '*.whl')))
      assertRegex(self, os.path.basename(single_wheel_output),
                               r'\A{}'.format(re.escape('fasthello-1.0.0+')))

  def test_pants_run(self):
    with temporary_dir() as tmp_dir:
      command=[
        '--pants-distdir={}'.format(tmp_dir),
        'run',
        '{}:main'.format(self.fasthello_project)]
      pants_run = self.run_pants(command=command)
      self.assert_success(pants_run)
      # Check that text was properly printed to stdout.
      self._assert_native_greeting(pants_run.stdout_data)

  def test_invalidation(self):
    """Test that the current version of a python_dist() is resolved after modifying its sources."""
    fasthello_run = '{}:main_with_no_conflict'.format(self.fasthello_install_requires_dir)

    with self.mock_buildroot(
        dirs_to_copy=[self.fasthello_install_requires_dir]) as buildroot, buildroot.pushd():
      run_target = lambda: self.run_pants_with_workdir(
        command=['run', fasthello_run],
        workdir=os.path.join(buildroot.new_buildroot, '.pants.d'),
        build_root=buildroot.new_buildroot,
      )

      unmodified_pants_run = run_target()
      self.assert_success(unmodified_pants_run)
      self.assertIn('Hello from C!\n', unmodified_pants_run.stdout_data)

      # Modify one of the source files for this target so that the output is different.
      c_source_file = os.path.join(self.fasthello_install_requires_dir, 'c_greet.c')
      with open(c_source_file, 'r') as f:
        orig_contents = f.read()
      modified_contents = re.sub('"Hello from C!"', '"Hello from C?"', orig_contents)
      with open(c_source_file, 'w') as f:
        f.write(modified_contents)

      modified_pants_run = run_target()
      self.assert_success(modified_pants_run)
      self.assertIn('Hello from C?\n', modified_pants_run.stdout_data)

  def test_pants_test(self):
    with temporary_dir() as tmp_dir:
      command=[
        '--pants-distdir={}'.format(tmp_dir),
        'test',
        '{}:fasthello'.format(self.fasthello_tests)]
      pants_run = self.run_pants(command=command)
      self.assert_success(pants_run)
      # Make sure that there is no wheel output when 'binary' goal is not invoked.
      self.assertEqual(len(glob.glob(os.path.join(tmp_dir, '*.whl'))), 0)

  def test_with_install_requires(self):
    with temporary_dir() as tmp_dir:
      pex = os.path.join(tmp_dir, 'main_with_no_conflict.pex')
      command=[
        '--pants-distdir={}'.format(tmp_dir),
        'run',
        '{}:main_with_no_conflict'.format(self.fasthello_install_requires_dir)]
      pants_run = self.run_pants(command=command)
      self.assert_success(pants_run)
      self.assertIn('United States', pants_run.stdout_data)
      command=['binary', '{}:main_with_no_conflict'.format(self.fasthello_install_requires_dir)]
      pants_run = self.run_pants(command=command)
      self.assert_success(pants_run)
      output = subprocess.check_output(pex).decode('utf-8')
      self.assertIn('United States', output)

  def test_with_conflicting_transitive_deps(self):
    command=['run', '{}:main_with_conflicting_dep'.format(self.fasthello_install_requires_dir)]
    pants_run = self.run_pants(command=command)
    self.assert_failure(pants_run)
    self.assertIn('pycountry', pants_run.stderr_data)
    self.assertIn('fasthello', pants_run.stderr_data)
    command=['binary', '{}:main_with_conflicting_dep'.format(self.fasthello_install_requires_dir)]
    pants_run = self.run_pants(command=command)
    self.assert_failure(pants_run)
    self.assertIn('pycountry', pants_run.stderr_data)
    self.assertIn('fasthello', pants_run.stderr_data)

  def test_binary_dep_isolation_with_multiple_targets(self):
    with temporary_dir() as tmp_dir:
      pex1 = os.path.join(tmp_dir, 'main_with_no_conflict.pex')
      pex2 = os.path.join(tmp_dir, 'main_with_no_pycountry.pex')
      command=[
        '--pants-distdir={}'.format(tmp_dir),
        'binary',
        '{}:main_with_no_conflict'.format(self.fasthello_install_requires_dir),
        '{}:main_with_no_pycountry'.format(self.fasthello_install_requires_dir)]
      pants_run = self.run_pants(command=command)
      self.assert_success(pants_run)
      # Check that the pex was built.
      self.assertTrue(os.path.isfile(pex1))
      self.assertTrue(os.path.isfile(pex2))
      # Check that the pex 1 runs.
      output = subprocess.check_output(pex1).decode('utf-8')
      self._assert_native_greeting(output)
      # Check that the pex 2 fails due to no python_dists leaked into it.
      try:
        subprocess.check_output(pex2)
      except subprocess.CalledProcessError as e:
        self.assertNotEqual(0, e.returncode)

  def test_pants_resolves_local_dists_for_current_platform_only(self):
    # Test that pants will override pants.ini platforms config when building
    # or running a target that depends on native (c or cpp) sources.
    with temporary_dir() as tmp_dir:
      pex = os.path.join(tmp_dir, 'main.pex')
      pants_ini_config = {
        'python-setup': {
          # If no targets exist declaring the nonexistent platform, this should be reduced to just
          # ['current'] in PythonNativeCode#check_build_for_current_platform_only().
          'platforms': ['current', 'this-platform-does_not-exist'],
        },
      }
      command=[
        '--pants-distdir={}'.format(tmp_dir),
        'run',
        '{}:main'.format(self.fasthello_project)]
      pants_run = self.run_pants(command=command, config=pants_ini_config)
      self.assert_success(pants_run)

      command=['binary', '{}:main'.format(self.fasthello_project)]
      pants_run = self.run_pants(command=command, config=pants_ini_config)
      self.assert_success(pants_run)
      # Check that the pex was built.
      self.assertTrue(os.path.isfile(pex))
      # Check that the pex runs.
      output = subprocess.check_output(pex).decode('utf-8')
      self._assert_native_greeting(output)

  def test_pants_tests_local_dists_for_current_platform_only(self):
    with temporary_dir() as tmp_dir:
      command=[
        '--pants-distdir={}'.format(tmp_dir),
        'test',
        '{}:fasthello'.format(self.fasthello_tests)]
      pants_run = self.run_pants(command=command, config={
        'python-setup': {
          'platforms': ['current'],
        },
      })
      self.assert_success(pants_run)

  def test_python_distribution_with_setup_requires(self):
    # Validate that setup_requires dependencies are present and functional.
    # PANTS_TEST_SETUP_REQUIRES triggers test functionality in this particular setup.py.
    with environment_as(PANTS_TEST_SETUP_REQUIRES='1'):
      command=['run', '{}:main'.format(self.hello_setup_requires)]
      pants_run = self.run_pants(command=command)

    command=['run', '{}:main'.format(self.hello_setup_requires)]
    pants_run = self.run_pants(command=command)

    with temporary_dir() as tmp_dir:
      pex = os.path.join(tmp_dir, 'main.pex')
      command=[
        '--pants-distdir={}'.format(tmp_dir),
        'binary',
        '{}:main'.format(self.hello_setup_requires),
      ]
      pants_run = self.run_pants(command=command)
      self.assert_success(pants_run)
      # Check that the pex was built.
      self.assertTrue(is_executable(pex))
      # Check that the pex runs.
      output = subprocess.check_output(pex).decode('utf-8')
      self.assertEqual('Hello, world!\n', output)
