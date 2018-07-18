# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import glob
import os
import re
from zipfile import ZipFile

from pants.backend.native.config.environment import Platform
from pants.option.scope import GLOBAL_SCOPE_CONFIG_SECTION
from pants.util.collections import assert_single_element
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import is_executable
from pants.util.process_handler import subprocess
from pants_test.backend.python.tasks.python_task_test_base import name_and_platform
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


def invoke_pex_for_output(pex_file_to_run):
  return subprocess.check_output([pex_file_to_run], stderr=subprocess.STDOUT)


class CTypesIntegrationTest(PantsRunIntegrationTest):

  _binary_target = 'testprojects/src/python/python_distribution/ctypes:bin'
  _binary_target_with_third_party = (
    'testprojects/src/python/python_distribution/ctypes_with_third_party:bin_with_third_party'
  )

  def test_run(self):
    pants_run = self.run_pants(command=['run', self._binary_target])
    self.assert_success(pants_run)

    # This is the entire output from main.py.
    self.assertIn('x=3, f(x)=17', pants_run.stdout_data)

  def test_binary(self):
    with temporary_dir() as tmp_dir:
      pants_run = self.run_pants(command=['binary', self._binary_target], config={
        GLOBAL_SCOPE_CONFIG_SECTION: {
          'pants_distdir': tmp_dir,
        }
      })

      self.assert_success(pants_run)

      # Check for the pex and for the wheel produced for our python_dist().
      pex = os.path.join(tmp_dir, 'bin.pex')
      self.assertTrue(is_executable(pex))

      # The + is because we append the target's fingerprint to the version. We test this version
      # string in test_build_local_python_distributions.py.
      wheel_glob = os.path.join(tmp_dir, 'ctypes_test-0.0.1+*.whl')
      wheel_dist_with_path = assert_single_element(glob.glob(wheel_glob))
      wheel_dist = re.sub('^{}{}'.format(re.escape(tmp_dir), os.path.sep), '', wheel_dist_with_path)

      dist_name, dist_version, wheel_platform = name_and_platform(wheel_dist)
      self.assertEqual(dist_name, 'ctypes_test')
      contains_current_platform = Platform.create().resolve_platform_specific({
        'darwin': lambda: wheel_platform.startswith('macosx'),
        'linux': lambda: wheel_platform.startswith('linux'),
      })
      self.assertTrue(contains_current_platform)

      # Verify that the wheel contains our shared libraries.
      wheel_files = ZipFile(wheel_dist_with_path).namelist()

      dist_versioned_name = '{}-{}.data'.format(dist_name, dist_version)
      for shared_lib_filename in ['libasdf-c.so', 'libasdf-cpp.so']:
        full_path_in_wheel = os.path.join(dist_versioned_name, 'data', shared_lib_filename)
        self.assertIn(full_path_in_wheel, wheel_files)

      # Execute the binary and ensure its output is correct.
      binary_run_output = invoke_pex_for_output(pex)
      self.assertIn('x=3, f(x)=17', binary_run_output)

  def test_ctypes_third_party_integration(self):
    pants_binary = self.run_pants(
      command=['clean-all', 'binary', self._binary_target_with_third_party]
    )
    self.assert_success(pants_binary)

    pants_run = self.run_pants(
      command=['clean-all', 'run', self._binary_target_with_third_party]
    )
    self.assert_success(pants_run)
    self.assertIn('Test worked!', pants_run.stdout_data)

    # Test cached run.
    pants_run = self.run_pants(
      command=['run', self._binary_target_with_third_party]
    )
    self.assert_success(pants_run)
    self.assertIn('Test worked!', pants_run.stdout_data)
