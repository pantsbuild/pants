# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ScopeTestIntegrationTest(PantsRunIntegrationTest):
  """Tests for the behavior of the 'test' scope.

  These tests involve a library which has the 'test' scope, meaning it should only be available at
  runtime, and only for junit tests.

  There is a junit_tests() target which depends on it, and checks for its existence at runtime (not
  compile time!) by using Class.forName().

  A binary is configured to also check for the existence of the class at runtime. The binary should
  compile (because the reference to the 'test' class is dynamic and thus not checked by javac), but
  not run (because the binary should not have access to 'test' scopes any time).
  """

  @classmethod
  def _spec(cls, name):
    return 'testprojects/src/java/org/pantsbuild/testproject/junit/testscope:{}'.format(name)

  def test_tests_pass(self):
    """This junit_tests() target tests for the presence of a particular class at runtime.

    It should be included because it has the 'test' scope.
    """
    self.assert_success(self.run_pants([
      '--no-java-strict-deps', 'test', self._spec('tests'),
    ]))

  def test_binary_compiles(self):
    """This should compile just fine, because the reference to the 'test' class is dynamic.

    This test is mostly just here to ensure the integrity of the binary besides the missing 'test'
    class. We want to make sure that the test-case below this one isn't failing just because of an
    unrelated syntax error.
    """
    self.assert_success(self.run_pants([
      '--no-java-strict-deps', 'compile', self._spec('bin'),
    ]))

  def test_binary_fails_to_run(self):
    "Ensure the binary does not have access to 'test'-scoped dependencies at runtime."
    self.assert_failure(self.run_pants([
      '--no-java-strict-deps', 'run', self._spec('bin'),
    ]))
