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


_LINUX_PLATFORM = "linux-x86_64"
_LINUX_WHEEL_SUBSTRING = "manylinux"
_OSX_PLATFORM = "macosx-10.13-x86_64"
_OSX_WHEEL_SUBSTRING = "macosx"


class PythonBinaryIntegrationTest(PantsRunIntegrationTest):

  @classmethod
  def use_pantsd_env_var(cls):
    """TODO(#7320): See the point about watchman."""
    return False

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

  def test_platform_defaults_to_config(self):
    self.platforms_test_impl(
      target_platforms=None,
      config_platforms=[_OSX_PLATFORM],
      want_present_platforms=[_OSX_WHEEL_SUBSTRING],
      want_missing_platforms=[_LINUX_PLATFORM],
    )

  def test_target_platform_without_config(self):
    self.platforms_test_impl(
      target_platforms=[_LINUX_PLATFORM],
      config_platforms=None,
      want_present_platforms=[_LINUX_WHEEL_SUBSTRING],
      want_missing_platforms=[_OSX_WHEEL_SUBSTRING],
    )

  def test_target_platform_overrides_config(self):
    self.platforms_test_impl(
      target_platforms=[_LINUX_PLATFORM],
      config_platforms=[_OSX_WHEEL_SUBSTRING],
      want_present_platforms=[_LINUX_WHEEL_SUBSTRING],
      want_missing_platforms=[_OSX_WHEEL_SUBSTRING],
    )

  def test_target_platform_narrows_config(self):
    self.platforms_test_impl(
      target_platforms=[_LINUX_PLATFORM],
      config_platforms=[_LINUX_WHEEL_SUBSTRING, _OSX_WHEEL_SUBSTRING],
      want_present_platforms=[_LINUX_WHEEL_SUBSTRING],
      want_missing_platforms=[_OSX_WHEEL_SUBSTRING],
    )

  def test_target_platform_expands_config(self):
    self.platforms_test_impl(
      target_platforms=[_LINUX_PLATFORM, _OSX_PLATFORM],
      config_platforms=[_LINUX_WHEEL_SUBSTRING],
      want_present_platforms=[_LINUX_WHEEL_SUBSTRING, _OSX_WHEEL_SUBSTRING],
    )

  def platforms_test_impl(
    self,
    target_platforms,
    config_platforms,
    want_present_platforms,
    want_missing_platforms=(),
  ):
    def numpy_deps(deps):
      return [d for d in deps if 'numpy' in d]
    def assertInAny(substring, collection):
      self.assertTrue(any(substring in d for d in collection),
        'Expected an entry matching "{}" in {}'.format(substring, collection))
    def assertNotInAny(substring, collection):
      self.assertTrue(all(substring not in d for d in collection),
        'Expected an entry matching "{}" in {}'.format(substring, collection))

    test_project = 'testprojects/src/python/cache_fields'
    test_build = os.path.join(test_project, 'BUILD')
    test_src = os.path.join(test_project, 'main.py')
    test_pex = 'dist/cache_fields.pex'

    with self.caching_config() as config, self.mock_buildroot() as buildroot, buildroot.pushd():
      config['python-setup'] = {
        'platforms': None
      }

      buildroot.write_file(test_src, '')

      buildroot.write_file(test_build,
        dedent("""
        python_binary(
          source='main.py',
          dependencies=[':numpy'],
          {target_platforms}
        )
        python_requirement_library(
          name='numpy',
          requirements=[
            python_requirement('numpy==1.14.5')
          ]
        )

        """.format(
          target_platforms="platforms = [{}],".format(", ".join(["'{}'".format(p) for p in target_platforms])) if target_platforms is not None else "",
        ))
      )
      # When only the linux platform is requested,
      # only linux wheels should end up in the pex.
      if config_platforms is not None:
        config['python-setup']['platforms'] = config_platforms
      result = self.run_pants_with_workdir(
        command=['binary', test_project],
        workdir=os.path.join(buildroot.new_buildroot, '.pants.d'),
        config=config,
        build_root=buildroot.new_buildroot,
        tee_output=True,
      )
      self.assert_success(result)

      with open_zip(test_pex) as z:
        deps = numpy_deps(z.namelist())
        for platform in want_present_platforms:
          assertInAny(platform, deps)
        for platform in want_missing_platforms:
          assertNotInAny(platform, deps)
