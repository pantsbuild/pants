# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import glob
import os
import re
from builtins import open

from pants.util.collections import assert_single_element
from pants.util.contextutil import temporary_dir
from pants.util.process_handler import subprocess
from pants_test.pants_run_integration_test import PantsRunIntegrationTest, daemon_blacklist
from pants_test.testutils.py2_compat import assertRegex


class BuildLocalPythonDistributionsIntegrationTest(PantsRunIntegrationTest):
  hello_install_requires_dir = 'testprojects/src/python/python_distribution/hello_with_install_requires'
  hello_setup_requires = 'examples/src/python/example/python_distribution/hello/setup_requires'
  py_dist_test = 'testprojects/tests/python/example_test/python_distribution'

  def _assert_nation_and_greeting(self, output, punctuation='!'):
    self.assertEquals("""\
hello{}
United States
""".format(punctuation), output)

  def test_pydist_binary(self):
    with temporary_dir() as tmp_dir:
      pex = os.path.join(tmp_dir, 'main_with_no_conflict.pex')
      command = [
        '--pants-distdir={}'.format(tmp_dir),
        'binary',
        '{}:main_with_no_conflict'.format(self.hello_install_requires_dir),
      ]
      pants_run = self.run_pants(command=command)
      self.assert_success(pants_run)
      # Check that the pex was built.
      self.assertTrue(os.path.isfile(pex))
      # Check that the pex runs.
      output = subprocess.check_output(pex).decode('utf-8')
      self._assert_nation_and_greeting(output)
      # Check that we have exactly one wheel output.
      single_wheel_output = assert_single_element(glob.glob(os.path.join(tmp_dir, '*.whl')))
      assertRegex(self, os.path.basename(single_wheel_output),
                  r'\A{}'.format(re.escape('hello_with_install_requires-1.0.0+')))

  def test_pydist_run(self):
    with temporary_dir() as tmp_dir:
      command=[
        '--pants-distdir={}'.format(tmp_dir),
        '--quiet',
        'run',
        '{}:main_with_no_conflict'.format(self.hello_install_requires_dir)]
      pants_run = self.run_pants(command=command)
      self.assert_success(pants_run)
      # Check that text was properly printed to stdout.
      self._assert_nation_and_greeting(pants_run.stdout_data)

  @daemon_blacklist('TODO: See #7320.')
  def test_pydist_invalidation(self):
    """Test that the current version of a python_dist() is resolved after modifying its sources."""
    hello_run = '{}:main_with_no_conflict'.format(self.hello_install_requires_dir)

    with self.mock_buildroot(
        dirs_to_copy=[self.hello_install_requires_dir]) as buildroot, buildroot.pushd():
      run_target = lambda: self.run_pants_with_workdir(
        command=['--quiet', 'run', hello_run],
        workdir=os.path.join(buildroot.new_buildroot, '.pants.d'),
        build_root=buildroot.new_buildroot,
      )

      unmodified_pants_run = run_target()
      self.assert_success(unmodified_pants_run)
      self._assert_nation_and_greeting(unmodified_pants_run.stdout_data)

      # Modify one of the source files for this target so that the output is different.
      py_source_file = os.path.join(
        self.hello_install_requires_dir, 'hello_package/hello.py')
      with open(py_source_file, 'r') as f:
        orig_contents = f.read()
      # Replace hello! with hello?
      modified_contents = re.sub('!', '?', orig_contents)
      with open(py_source_file, 'w') as f:
        f.write(modified_contents)

      modified_pants_run = run_target()
      self.assert_success(modified_pants_run)
      self._assert_nation_and_greeting(modified_pants_run.stdout_data, punctuation='?')

  def test_pydist_test(self):
    with temporary_dir() as tmp_dir:
      command=[
        '--pants-distdir={}'.format(tmp_dir),
        'test',
        self.py_dist_test,
      ]
      pants_run = self.run_pants(command=command)
      self.assert_success(pants_run)
      # Make sure that there is no wheel output when 'binary' goal is not invoked.
      self.assertEqual(0, len(glob.glob(os.path.join(tmp_dir, '*.whl'))))
