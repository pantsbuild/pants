# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT


class DeclaredDepsIntegrationTest(BaseCompileIT):

  def test_direct_source_dep(self):
    # Should fail with strict deps.
    self.do_test_success_and_failure(
      'testprojects/src/java/org/pantsbuild/testproject/missingdirectdepswhitelist',
      ['--no-java-strict-deps'],
      ['--java-strict-deps'],
    )

  def test_direct_jar_dep(self):
    # Should fail with strict deps.
    self.do_test_success_and_failure(
      'testprojects/src/java/org/pantsbuild/testproject/missingjardepswhitelist',
      ['--no-java-strict-deps'],
      ['--java-strict-deps'],
    )

  def test_missing_source_dep_whitelist(self):
    # Should fail when it is not whitelisted.
    target = 'testprojects/src/java/org/pantsbuild/testproject/missingdirectdepswhitelist'
    self.do_test_success_and_failure(
      target,
      ['--compile-jvm-dep-check-missing-deps-whitelist=["{}"]'.format(target)],
      [],
      shared_args=[
        '--compile-jvm-dep-check-missing-direct-deps=fatal',
        '--no-java-strict-deps',
      ],
    )

  def test_missing_jar_dep_whitelist(self):
    # Should fail when it is not whitelisted.
    target = 'testprojects/src/java/org/pantsbuild/testproject/missingjardepswhitelist'
    self.do_test_success_and_failure(
      target,
      ['--compile-jvm-dep-check-missing-deps-whitelist=["{}"]'.format(target)],
      [],
      shared_args=[
        '--compile-jvm-dep-check-missing-direct-deps=fatal',
        '--no-java-strict-deps',
      ],
    )
