# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT
from pants_test.backend.jvm.tasks.jvm_compile.utils import provide_compile_strategies


class JvmExamplesCompileIntegrationTest(BaseCompileIT):
  @provide_compile_strategies
  def test_java_src_zinc_compile(self, strategy):
    self.do_test_compile('examples/src/java/::', strategy, extra_args='--compile-zinc-java-enabled')

  @provide_compile_strategies
  def test_java_tests_zinc_compile(self, strategy):
    self.do_test_compile('examples/tests/java/::', strategy, extra_args='--compile-zinc-java-enabled')
