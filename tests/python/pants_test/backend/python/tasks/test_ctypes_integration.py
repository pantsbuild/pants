# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import glob
import os
from zipfile import ZipFile

from pants.backend.native.config.environment import Platform
from pants.base.build_environment import get_buildroot
from pants.option.scope import GLOBAL_SCOPE_CONFIG_SECTION
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import is_executable
from pants.util.process_handler import subprocess
from pants_test.backend.python.tasks.python_task_test_base import name_and_platform
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


def invoke_pex_for_output(pex_file_to_run):
  return subprocess.check_output([pex_file_to_run], stderr=subprocess.STDOUT)


class CTypesIntegrationTest(PantsRunIntegrationTest):

  _binary_target = 'testprojects/src/python/python_distribution/ctypes:bin'
  _binary_target_with_header_only_third_party = ('testprojects/src/python/'
                                                'python_distribution/'
                                                'ctypes_with_third_party:bin_with_third_party')

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

      wheel_glob = os.path.join(tmp_dir, 'ctypes_test-0.0.1-*.whl')
      globbed_wheel = glob.glob(wheel_glob)
      self.assertEqual(len(globbed_wheel), 1)
      wheel_dist = globbed_wheel[0]

      _, _, wheel_platform = name_and_platform(wheel_dist)
      contains_current_platform = Platform.create().resolve_platform_specific({
        'darwin': lambda: wheel_platform.startswith('macosx'),
        'linux': lambda: wheel_platform.startswith('linux'),
      })
      self.assertTrue(contains_current_platform)

      # Verify that the wheel contains our shared libraries.
      wheel_files = ZipFile(wheel_dist).namelist()

      for shared_lib_filename in ['libasdf-c.so', 'libasdf-cpp.so']:
        full_path_in_wheel = os.path.join('ctypes_test-0.0.1.data', 'data', shared_lib_filename)
        self.assertIn(full_path_in_wheel, wheel_files)

      # Execute the binary and ensure its output is correct.
      binary_run_output = invoke_pex_for_output(pex)
      self.assertEqual('x=3, f(x)=17\n', binary_run_output)

  def test_header_only_third_party_integration(self):
    with temporary_dir() as tmp_dir:
      cereal_outfile = os.path.join(get_buildroot(), 'out.cereal')
      try:
        pants_run = self.run_pants(
            command=['clean-all', 'run', self._binary_target_with_header_only_third_party],
            config={
              GLOBAL_SCOPE_CONFIG_SECTION: {
                'pants_distdir': tmp_dir,
              }
            }
        )
        self.assert_success(pants_run)
      finally:
        if os.path.exists(cereal_outfile):
          os.remove(cereal_outfile)
