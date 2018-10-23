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
from pants.util.dirutil import is_executable, read_file, safe_file_dump
from pants.util.process_handler import subprocess
from pants_test.backend.python.tasks.python_task_test_base import name_and_platform
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


def invoke_pex_for_output(pex_file_to_run):
  return subprocess.check_output([pex_file_to_run], stderr=subprocess.STDOUT)


class CTypesIntegrationTest(PantsRunIntegrationTest):

  _binary_target = 'testprojects/src/python/python_distribution/ctypes:bin'
  _binary_interop_target_dir = 'testprojects/src/python/python_distribution/ctypes_interop'
  _binary_target_with_interop = '{}:bin'.format(_binary_interop_target_dir)
  _wrapped_math_build_file = os.path.join(_binary_interop_target_dir, 'wrapped-math', 'BUILD')
  _binary_target_with_third_party = (
    'testprojects/src/python/python_distribution/ctypes_with_third_party:bin_with_third_party'
  )

  def test_ctypes_run(self):
    pants_run = self.run_pants(command=['-q', 'run', self._binary_target])
    self.assert_success(pants_run)

    self.assertEqual('x=3, f(x)=17\n', pants_run.stdout_data)

  def test_ctypes_binary(self):
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
      self.assertEqual('x=3, f(x)=17\n', binary_run_output)

  def test_ctypes_native_language_interop(self):
    # TODO: consider making this mock_buildroot/run_pants_with_workdir into a
    # PantsRunIntegrationTest method!
    with self.mock_buildroot(
        dirs_to_copy=[self._binary_interop_target_dir]) as buildroot, buildroot.pushd():

      # Replace strict_deps=False with nothing so we can override it (because target values for this
      # option take precedence over subsystem options).
      orig_wrapped_math_build = read_file(self._wrapped_math_build_file)
      without_strict_deps_wrapped_math_build = re.sub(
        'strict_deps=False,', '', orig_wrapped_math_build)
      safe_file_dump(self._wrapped_math_build_file, without_strict_deps_wrapped_math_build)

      # This should fail because it does not turn on strict_deps for a target which requires it.
      pants_binary_strict_deps_failure = self.run_pants_with_workdir(
        command=['binary', self._binary_target_with_interop],
        # Explicitly set to True (although this is the default).
        config={'native-build-settings': {'strict_deps': True}},
        workdir=os.path.join(buildroot.new_buildroot, '.pants.d'),
        build_root=buildroot.new_buildroot)
      self.assert_failure(pants_binary_strict_deps_failure)
      self.assertIn("fatal error: 'some_math.h' file not found",
                    pants_binary_strict_deps_failure.stdout_data)

    pants_run_interop = self.run_pants(['-q', 'run', self._binary_target_with_interop], config={
      'native-build-settings': {
        'strict_deps': False,
      },
    })
    self.assert_success(pants_run_interop)
    self.assertEqual('x=3, f(x)=299\n', pants_run_interop.stdout_data)

  def test_ctypes_third_party_integration(self):
    pants_binary = self.run_pants(['binary', self._binary_target_with_third_party])
    self.assert_success(pants_binary)

    pants_run = self.run_pants(['-q', 'run', self._binary_target_with_third_party])
    self.assert_success(pants_run)
    self.assertIn('Test worked!\n', pants_run.stdout_data)

    # Test cached run.
    pants_run = self.run_pants(
      command=['-q', 'run', self._binary_target_with_third_party]
    )
    self.assert_success(pants_run)
    self.assertIn('Test worked!\n', pants_run.stdout_data)

  def test_pants_native_source_detection_for_local_ctypes_dists_for_current_platform_only(self):
    """Test that `./pants run` respects platforms when the closure contains native sources.

    To do this, we need to setup a pants.ini that contains two platform defauts: (1) "current" and
    (2) a different platform than the one we are currently running on. The python_binary() target
    below is declared with `platforms="current"`.
    """
    # Clean all to rebuild requirements pex.
    command = [
      'run',
      'testprojects/src/python/python_distribution/ctypes:bin'
    ]
    pants_run = self.run_pants(command=command, config={
      'python-setup': {
        'platforms': ['current', 'this-platform-does_not-exist']
      },
    })
    self.assert_success(pants_run)
    self.assertIn('x=3, f(x)=17', pants_run.stdout_data)

  '''
  def test_native_compiler_option_sets_integration(self):
    """Test that native compilation includes extra compiler flags from target definitions.

    This target has ndebug=True and glibcxx_use_cxx11_abi=False.
    If either of these are not present or negated, this test will fail.
    """
    command = [
      'run',
      'testprojects/src/python/python_distribution/ctypes_with_extra_compiler_flags:bin'
    ]
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)
    self.assertIn('x=3, f(x)=126', pants_run.stdout_data)
  '''
