# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ScopeProvidedIntegrationTest(PantsRunIntegrationTest):
  """Tests "provided" emulation (having scope='compile test' and transitive=False)."""

  @classmethod
  def _spec(cls, name):
    return 'testprojects/src/java/org/pantsbuild/testproject/provided:{}'.format(name)

  def test_leaf_binary(self):
    self.assert_success(self.run_pants([
      '--no-java-strict-deps', 'run', self._spec('a-bin')
    ]))

  def test_compile_with_provided_passes(self):
    self.assert_success(self.run_pants([
      '--no-java-strict-deps', 'compile', self._spec('b-bin')
    ]))

  def test_run_with_provided_fails(self):
    self.assert_failure(self.run_pants([
      '--no-java-strict-deps', 'run', self._spec('b-bin')
    ]))

  def test_compile_with_transitive_provided_fails(self):
    self.assert_failure(self.run_pants([
      '--no-java-strict-deps', 'compile', self._spec('c-bin')
    ]))

  def test_run_with_provided_and_explicit_dependency(self):
    self.assert_success(self.run_pants([
      '--no-java-strict-deps', 'run', self._spec('c-with-direct-dep')
    ]))

  def test_run_with_provided_and_transitive_explicit_dependency(self):
    self.assert_success(self.run_pants([
      '--no-java-strict-deps', 'run', self._spec('c-with-transitive-dep')
    ]))


class ScopeProvidedShadowingIntegrationTest(PantsRunIntegrationTest):

  @classmethod
  def _spec(cls, name):
    return 'testprojects/maven_layout/provided_patching/leaf:{}'.format(name)

  def test_shadow_one(self):
    run = self.run_pants([
      '--no-java-strict-deps', 'run', self._spec('one')
    ])
    self.assert_success(run)
    self.assertIn('Shadow One:Shadow One', run.stdout_data)

  def test_shadow_two(self):
    run = self.run_pants([
      '--no-java-strict-deps', 'run', self._spec('two')
    ])
    self.assert_success(run)
    self.assertIn('Shadow Two:Shadow Two', run.stdout_data)

  def test_shadow_three(self):
    run = self.run_pants([
      '--no-java-strict-deps', 'run', self._spec('three')
    ])
    self.assert_success(run)
    self.assertIn('Shadow Three:Shadow Three', run.stdout_data)

  def test_shadow_fail(self):
    run = self.run_pants([
      '--no-java-strict-deps', 'compile', self._spec('fail')
    ])
    self.assert_failure(run)

  def test_shadow_test_passes(self):
    run = self.run_pants([
      '--no-java-strict-deps', 'test', self._spec('test')
    ])
    self.assert_success(run)
