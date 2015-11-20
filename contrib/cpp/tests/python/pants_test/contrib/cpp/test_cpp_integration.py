# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from unittest import skipUnless

from pants_test.pants_run_integration_test import PantsRunIntegrationTest

from pants.contrib.cpp.toolchain.cpp_toolchain import CppToolchain


def have_compiler():
  try:
    CppToolchain().compiler
    return True
  except CppToolchain.Error:
    return False


class CppIntegrationTest(PantsRunIntegrationTest):
  """Integration test for cpp which builds libraries and builds and runs binaries."""

  # TODO(dhamon): Move these to the test folder and keep the example folder for more
  # complete examples.
  TEST_SIMPLE_BINARY_TARGET = 'contrib/cpp/examples/src/cpp/example:hello_pants'
  TEST_BINARY_WITH_LIBRARY_TARGET = 'contrib/cpp/examples/src/cpp/calcsqrt'
  TEST_LIBRARY_TARGET = 'contrib/cpp/examples/src/cpp/example/hello'
  TEST_RUN_TARGET = TEST_SIMPLE_BINARY_TARGET

  skipUnlessHaveCompiler = skipUnless(have_compiler(),
                                      reason='cpp integration tests require compiler')

  @skipUnlessHaveCompiler
  def test_cpp_library(self):
    self._binary_test(self.TEST_LIBRARY_TARGET)

  @skipUnlessHaveCompiler
  def test_cpp_library_compile(self):
    self._compile_test(self.TEST_LIBRARY_TARGET)

  @skipUnlessHaveCompiler
  def test_cpp_binary(self):
    self._binary_test(self.TEST_SIMPLE_BINARY_TARGET)

  @skipUnlessHaveCompiler
  def test_cpp_binary_compile(self):
    self._compile_test(self.TEST_SIMPLE_BINARY_TARGET)

  @skipUnlessHaveCompiler
  def test_cpp_binary_with_library(self):
    self._binary_test(self.TEST_BINARY_WITH_LIBRARY_TARGET)

  @skipUnlessHaveCompiler
  def test_cpp_binary_with_library_compile(self):
    self._compile_test(self.TEST_BINARY_WITH_LIBRARY_TARGET)

  @skipUnlessHaveCompiler
  def test_cpp_run(self):
    pants_run = self.run_pants(['run', self.TEST_RUN_TARGET])
    self.assert_success(pants_run)
    self.assertIn('[cpp-run]\nHello, pants!\nGoodbye, pants!\n',
                  pants_run.stdout_data)

  def _run_with_cache(self, task, target):
    with self.temporary_cachedir() as cache:
      args = [
        'clean-all',
        task,
        "--cache-write-to=['{}']".format(cache),
        "--cache-read-from=['{}']".format(cache),
        target,
        '-ldebug',
      ]

      pants_run = self.run_pants(args)
      self.assert_success(pants_run)
      self.assertIn('No cached artifacts', pants_run.stdout_data)
      self.assertIn('Caching artifacts', pants_run.stdout_data)

      pants_run = self.run_pants(args)
      self.assert_success(pants_run)
      self.assertIn('Using cached artifacts', pants_run.stdout_data)
      self.assertNotIn('No cached artifacts', pants_run.stdout_data)

  def _binary_test(self, target):
    self._run_with_cache('binary', target)

  def _compile_test(self, target):
    self._run_with_cache('compile', target)
