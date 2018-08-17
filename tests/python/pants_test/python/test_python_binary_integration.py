# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import functools
import os
from contextlib import contextmanager
from textwrap import dedent

from pex.pex_info import PexInfo

from pants.util.contextutil import open_zip, temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PythonBinaryIntegrationTest(PantsRunIntegrationTest):
  @staticmethod
  @contextmanager
  def caching_config():
    """Creates a temporary directory and returns a pants configuration for passing to pants_run."""
    with temporary_dir() as tmp_dir:
      yield {
        'cache': {
          'read': True,
          'write': True,
          'read_from': [tmp_dir],
          'write_to': [tmp_dir]
        }
      }

  def assert_pex_attribute(self, pex, attr, value):
    self.assertTrue(os.path.exists(pex))
    pex_info = PexInfo.from_pex(pex)
    self.assertEqual(getattr(pex_info, attr), value)

  def test_zipsafe_caching(self):
    test_project = 'testprojects/src/python/cache_fields'
    test_build = os.path.join(test_project, 'BUILD')
    test_src = os.path.join(test_project, 'main.py')
    test_pex = 'dist/cache_fields.pex'
    zipsafe_target_tmpl = "python_binary(source='main.py', zip_safe={})"

    with self.caching_config() as config, self.mock_buildroot() as buildroot, buildroot.pushd():
      build = functools.partial(
        self.run_pants_with_workdir,
        command=['binary', test_project],
        workdir=os.path.join(buildroot.new_buildroot, '.pants.d'),
        config=config,
        build_root=buildroot.new_buildroot
      )

      buildroot.write_file(test_src, '')

      # Create a pex from a simple python_binary target and assert it has zip_safe=True (default).
      buildroot.write_file(test_build, "python_binary(source='main.py')")
      self.assert_success(build())
      self.assert_pex_attribute(test_pex, 'zip_safe', True)

      # Simulate a user edit by adding zip_safe=False to the target and check the resulting pex.
      buildroot.write_file(test_build, zipsafe_target_tmpl.format('False'))
      self.assert_success(build())
      self.assert_pex_attribute(test_pex, 'zip_safe', False)

      # Simulate a user edit by adding zip_safe=True to the target and check the resulting pex.
      buildroot.write_file(test_build, zipsafe_target_tmpl.format('True'))
      self.assert_success(build())
      self.assert_pex_attribute(test_pex, 'zip_safe', True)

  def test_platforms(self):
    test_project = 'testprojects/src/python/cache_fields'
    test_build = os.path.join(test_project, 'BUILD')
    test_src = os.path.join(test_project, 'main.py')
    test_pex = 'dist/cache_fields.pex'
    numpy_manylinux_dep = '.deps/numpy-1.14.5-cp27-cp27m-manylinux1_x86_64.whl/numpy/__init__.py'
    numpy_macos_dep = '.deps/numpy-1.14.5-cp27-cp27m-macosx_10_6_intel.macosx_10_9_intel.macosx_10_9_x86_64.macosx_10_10_intel.macosx_10_10_x86_64.whl/numpy/__init__.py'

    with self.caching_config() as config, self.mock_buildroot() as buildroot, buildroot.pushd():
      config['python-setup'] = {
        'platforms': None
      }
      build = functools.partial(
        self.run_pants_with_workdir,
        command=['binary', test_project],
        workdir=os.path.join(buildroot.new_buildroot, '.pants.d'),
        config=config,
        build_root=buildroot.new_buildroot
      )

      buildroot.write_file(test_src, '')

      buildroot.write_file(test_build,
        dedent("""
        python_binary(source='main.py', dependencies=[':numpy'])
        python_requirement_library(
          name='numpy',
          requirements=[
            python_requirement('numpy==1.14.5')
          ]
        )

        """)
      )
      # When only the linux platform is requested,
      # only linux wheels should end up in the pex.
      config['python-setup']['platforms'] = ['linux-x86_64']
      build()

      with open_zip(test_pex) as z:
        namelist = z.namelist()
        self.assertIn(
          numpy_manylinux_dep,
          namelist)
        self.assertNotIn(
          numpy_macos_dep,
          namelist)

      # When both linux and macosx platforms are requested,
      # wheels for both should end up in the pex.
      config['python-setup']['platforms'] = [
        'linux-x86_64',
        'macosx-10.13-x86_64']
      build()

      with open_zip(test_pex) as z:
        namelist = z.namelist()
        self.assertIn(
          numpy_manylinux_dep,
          namelist)
        self.assertIn(
          numpy_macos_dep,
          namelist)
