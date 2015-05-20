# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.util.contextutil import temporary_dir
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT
from pants_test.testutils.compile_strategy_utils import provide_compile_strategies


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
        workdir, 'examples/src/java/org/pantsbuild/example/hello/main', strategy,
        extra_args=['--compile-zinc-java-enabled', '-ldebug'], clean_all=True
      )
      # self.assertTrue('Attempting to call com.sun.tools.javac.api.JavacTool' in pants_run.stdout_data)
      self.assertTrue('Attempting to call javac directly' in pants_run.stdout_data)
      self.assertFalse('Forking javac' in pants_run.stdout_data)

  @unittest.skip("""
    Zinc 1.0.3 isn't published yet.
    Don't forget to uncomment and replace an assertion in #test_in_process above
    by moving to sbt 0.13.8 the output will be a bit different.
  """)
  @provide_compile_strategies
  def test_log_level(self, strategy):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      target = 'testprojects/src/java/org/pantsbuild/testproject/dummies:compilation_failure_target'
      pants_run = self.run_test_compile(
        workdir, target, strategy, extra_args=['--compile-zinc-java-enabled', '--no-color'], clean_all=True
      )
      self.assertTrue('[warn] sun.security.x509.X500Name' in pants_run.stdout_data)
      self.assertTrue('[error] System2.out' in pants_run.stdout_data)
