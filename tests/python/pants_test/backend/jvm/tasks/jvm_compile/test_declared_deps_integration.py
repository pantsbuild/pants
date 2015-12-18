# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT


DIR_DEPS_WHITELISTED = 'testprojects/src/java/org/pantsbuild/testproject/missingdirectdepswhitelist'
JAR_DEPS_WHITELISTED = 'testprojects/src/java/org/pantsbuild/testproject/missingjardepswhitelist'


class DeclaredDepsIntegrationTest(BaseCompileIT):

  def test_direct_source_dep(self):
    # Should fail with strict deps.
    self.do_test_success_and_failure(
      DIR_DEPS_WHITELISTED,
      ['--no-java-strict-deps'],
      ['--java-strict-deps'],
    )

  def test_direct_jar_dep(self):
    # Should fail with strict deps.
    self.do_test_success_and_failure(
      JAR_DEPS_WHITELISTED,
      ['--no-java-strict-deps'],
      ['--java-strict-deps'],
    )

  def test_invalid_subsystem_option_location(self):
    with self.do_test_compile(JAR_DEPS_WHITELISTED,
                              expect_failure=True,
                              extra_args=['--no-java-compile-zinc-strict-deps']):
      # Expected to fail due to passing the argument to a task-specific instance of the
      # subsystem, rather than globally.
      pass

  def test_missing_source_dep_whitelist(self):
    # Should fail when it is not whitelisted.
    self.do_test_success_and_failure(
      DIR_DEPS_WHITELISTED,
      ['--compile-jvm-dep-check-missing-deps-whitelist=["{}"]'.format(DIR_DEPS_WHITELISTED)],
      [],
      shared_args=[
        '--compile-jvm-dep-check-missing-direct-deps=fatal',
        '--no-java-strict-deps',
      ],
    )

  def test_missing_jar_dep_whitelist(self):
    # Should fail when it is not whitelisted.
    self.do_test_success_and_failure(
      JAR_DEPS_WHITELISTED,
      ['--compile-jvm-dep-check-missing-deps-whitelist=["{}"]'.format(JAR_DEPS_WHITELISTED)],
      [],
      shared_args=[
        '--compile-jvm-dep-check-missing-direct-deps=fatal',
        '--no-java-strict-deps',
      ],
    )
