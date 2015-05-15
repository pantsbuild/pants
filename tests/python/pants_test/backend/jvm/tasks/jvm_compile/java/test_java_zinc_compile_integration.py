# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.util.contextutil import temporary_dir
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT
from pants_test.backend.jvm.tasks.jvm_compile.utils import provide_compile_strategies


class JvmExamplesCompileIntegrationTest(BaseCompileIT):
  @provide_compile_strategies
  def test_java_src_zinc_compile(self, strategy):
    self.do_test_compile('examples/src/java/::', strategy, extra_args=['--compile-zinc-java-enabled'])

  @provide_compile_strategies
  def test_java_tests_zinc_compile(self, strategy):
    self.do_test_compile('examples/tests/java/::', strategy, extra_args=['--compile-zinc-java-enabled'])

  @provide_compile_strategies
  def test_in_process(self, strategy):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      pants_run = self.run_test_compile(
        workdir, 'examples/tests/java/::', strategy, extra_args=['--compile-zinc-java-enabled', '-ldebug']
      )
      self.assertTrue('Attempting to call javac directly' in pants_run.stdout_data)
      self.assertFalse('Forking javac' in pants_run.stdout_data)
