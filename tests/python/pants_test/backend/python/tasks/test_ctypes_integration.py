# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import glob
import os
from zipfile import ZipFile

from pants.backend.native.config.environment import Platform
from pants.option.scope import GLOBAL_SCOPE_CONFIG_SECTION
from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class CTypesIntegrationTest(PantsRunIntegrationTest):

  _binary_target = 'testprojects/src/python/python_distribution/ctypes:bin'

  @staticmethod
  def _name_and_platform(whl):
    # The wheel filename is of the format
    # {distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl
    # See https://www.python.org/dev/peps/pep-0425/.
    # We don't care about the python or abi versions (they depend on what we're currently
    # running on), we just want to make sure we have all the platforms we expect.
    parts = os.path.splitext(whl)[0].split('-')
    dist = parts[0]
    version = parts[1]
    platform_tag = parts[-1]
    return '{}-{}'.format(dist, version), platform_tag

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
      self.assertTrue(os.path.isfile(pex))

      wheel_glob = os.path.join(tmp_dir, 'ctypes_test-0.0.1-*.whl')
      globbed_wheel = glob.glob(wheel_glob)
      self.assertEqual(len(globbed_wheel), 1)
      wheel_dist = globbed_wheel[0]

      wheel_name, wheel_platform = self._name_and_platform(wheel_dist)
      cur_platform = Platform.create()
      self.assertEqual(wheel_platform, 'current')

      # Verify that the wheel contains our shared libraries.
      wheel_files = ZipFile(wheel_dist).namelist()

      for shared_lib_filename in ['libasdf-c.so', 'libasdf-cpp.so']:
        full_path_in_wheel = os.path.join('ctypes_test-0.0.1.data', 'data', shared_lib_filename)
        self.assertIn(full_path_in_wheel, wheel_files)
