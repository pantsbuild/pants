# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import glob
import os
import re
from zipfile import ZipFile

from pants.backend.native.config.environment import Platform
from pants.backend.native.subsystems.native_build_settings import ToolchainVariant
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

  _binary_target_dir = 'testprojects/src/python/python_distribution/ctypes'
  _binary_target = '{}:bin'.format(_binary_target_dir)
  _binary_interop_target_dir = 'testprojects/src/python/python_distribution/ctypes_interop'
  _binary_target_with_interop = '{}:bin'.format(_binary_interop_target_dir)
  _wrapped_math_build_file = os.path.join(_binary_interop_target_dir, 'wrapped-math', 'BUILD')
  _binary_target_with_third_party = (
    'testprojects/src/python/python_distribution/ctypes_with_third_party:bin_with_third_party'
  )
  _binary_target_with_compiler_option_sets = (
    'testprojects/src/python/python_distribution/ctypes_with_extra_compiler_flags:bin'
  )

  def test_ctypes_run(self):
    pants_run = self.run_pants(command=['-q', 'run', self._binary_target])
    self.assert_success(pants_run)

    self.assertEqual('x=3, f(x)=17\n', pants_run.stdout_data)

  def test_ctypes_binary_creation(self):
    """Create a python_binary() with all native toolchain variants, and test the result."""
    # TODO: this pattern could be made more ergonomic for `enum()`, along with exhaustiveness
    # checking.
    for variant in ToolchainVariant.allowed_values:
      self._assert_ctypes_binary(variant)

  _compiler_names_for_variant = {
    'gnu': ['gcc', 'g++'],
    'llvm': ['clang', 'clang++'],
  }

  # All of our toolchains currently use the C++ compiler's filename as argv[0] for the linker.
  _linker_names_for_variant = {
    'gnu': ['g++'],
    'llvm': ['clang++'],
  }

  def _assert_ctypes_binary(self, toolchain_variant):
    with temporary_dir() as tmp_dir:
      pants_run = self.run_pants(command=['binary', self._binary_target], config={
        GLOBAL_SCOPE_CONFIG_SECTION: {
          'pants_distdir': tmp_dir,
        },
        'native-build-settings': {
          'toolchain_variant': toolchain_variant,
        },
      })

      self.assert_success(pants_run)

      # Check that we have selected the appropriate compilers for our selected toolchain variant,
      # for both C and C++ compilation.
      for compiler_name in self._compiler_names_for_variant[toolchain_variant]:
        self.assertIn("selected compiler exe name: '{}'".format(compiler_name),
                      pants_run.stdout_data)

      for linker_name in self._linker_names_for_variant[toolchain_variant]:
        self.assertIn("selected linker exe name: '{}'".format(linker_name),
                      pants_run.stdout_data)

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
      self.assertEqual(b'x=3, f(x)=17\n', binary_run_output)

  def test_invalidation_ctypes(self):
    """Test that the current version of a python_dist() is resolved after modifying its sources."""
    with temporary_dir() as tmp_dir:
      with self.mock_buildroot(
          dirs_to_copy=[self._binary_target_dir]) as buildroot, buildroot.pushd():

        def run_target(goal):
          return self.run_pants_with_workdir(
            command=[goal, self._binary_target],
            workdir=os.path.join(buildroot.new_buildroot, '.pants.d'),
            build_root=buildroot.new_buildroot,
            config={
              GLOBAL_SCOPE_CONFIG_SECTION: {
                'pants_distdir': tmp_dir,
              },
            },
          )

        output_pex = os.path.join(tmp_dir, 'bin.pex')

        initial_result_message = 'x=3, f(x)=17'

        unmodified_pants_run = run_target('run')
        self.assert_success(unmodified_pants_run)
        self.assertIn(initial_result_message, unmodified_pants_run.stdout_data)

        unmodified_pants_binary_create = run_target('binary')
        self.assert_success(unmodified_pants_binary_create)
        binary_run_output = invoke_pex_for_output(output_pex)
        self.assertIn(initial_result_message, binary_run_output)

        # Modify one of the source files for this target so that the output is different.
        cpp_source_file = os.path.join(self._binary_target_dir, 'some_more_math.cpp')
        with open(cpp_source_file, 'r') as f:
          orig_contents = f.read()
        modified_contents = re.sub(r'3', '4', orig_contents)
        with open(cpp_source_file, 'w') as f:
          f.write(modified_contents)

        modified_result_message = 'x=3, f(x)=28'

        modified_pants_run = run_target('run')
        self.assert_success(modified_pants_run)
        self.assertIn(modified_result_message, modified_pants_run.stdout_data)

        modified_pants_binary_create = run_target('binary')
        self.assert_success(modified_pants_binary_create)
        binary_run_output = invoke_pex_for_output(output_pex)
        self.assertIn(modified_result_message, binary_run_output)

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

  def test_pants_native_source_detection_for_local_ctypes_dists_for_current_platform_only(self):
    """Test that `./pants run` respects platforms when the closure contains native sources.

    To do this, we need to setup a pants.ini that contains two platform defauts: (1) "current" and
    (2) a different platform than the one we are currently running on. The python_binary() target
    below is declared with `platforms="current"`.
    """
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

  def test_native_compiler_option_sets_integration(self):
    """Test that native compilation includes extra compiler flags from target definitions.

    This target uses the ndebug and asdf option sets.
    If either of these are not present (disabled), this test will fail.
    """
    command = [
      'run',
      self._binary_target_with_compiler_option_sets
    ]
    pants_run = self.run_pants(command=command, config={
      'native-build-step.cpp-compile-settings': {
        'compiler_option_sets_enabled_args': {
          'asdf': ['-D_ASDF=1'],
        },
        'compiler_option_sets_disabled_args': {
          'asdf': ['-D_ASDF=0'],
        }
      },
    })
    self.assert_success(pants_run)
    self.assertIn('x=3, f(x)=12600000', pants_run.stdout_data)
