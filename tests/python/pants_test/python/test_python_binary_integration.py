# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import functools
import os
from contextlib import contextmanager

from parameterized import parameterized
from pex.pex_info import PexInfo

from pants.util.contextutil import temporary_dir
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

  @parameterized.expand([
    (True, True, True),
    (True, False, False),
    (False, False, False),
    # If allow_sdist_builds is false, resolve will fail before attempting to build binary
    (False, True, False)
  ])
  def test_allow_sdist_builds(self, allow_sdist_builds, allow_build, expect_success):
    test_project = 'testprojects/src/python/sdist_builds'
    test_build = os.path.join(test_project, 'BUILD')
    test_src = os.path.join(test_project, 'main.py')

    with self.caching_config() as config, self.mock_buildroot() as buildroot, buildroot.pushd():
      build = functools.partial(
        self.run_pants_with_workdir,
        command=['clean-all', 'binary', '--python-setup-allow-sdist-builds=%s' % allow_sdist_builds,
                 '--python-setup-resolver-cache-dir="%s"' % os.path.join(buildroot.new_buildroot, 'python_cache/requirements'),
                 test_project],
        workdir=os.path.join(buildroot.new_buildroot, '.pants.d'),
        config=config,
        build_root=buildroot.new_buildroot
      )

      buildroot.write_file(test_src, '')

      # Create a pex from a simple python_binary target and assert it has zip_safe=True (default)
      buildroot.write_file(
        test_build,
        '''
python_binary(
  sources='main.py',
  build={allow_build},
  dependencies=[':pyhelloworld3'],
)

python_requirement_library(
    name = "pyhelloworld3",
    requirements = [
        python_requirement("pyhelloworld3==1.0.0"),
    ],
)'''.format(allow_build=allow_build))
      if expect_success:
        self.assert_success(build())
      else:
        self.assert_failure(build())
