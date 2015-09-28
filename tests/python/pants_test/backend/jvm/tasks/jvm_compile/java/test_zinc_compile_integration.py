# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.util.contextutil import temporary_dir
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT


class ZincCompileIntegrationTest(BaseCompileIT):

  def test_java_src_zinc_compile(self):
    with self.do_test_compile('examples/src/java/::', extra_args=['--no-compile-java-use-jmake']):
      # run succeeded as expected
      pass

  def test_java_tests_zinc_compile(self):
    with self.do_test_compile('examples/tests/java/::', extra_args=['--no-compile-java-use-jmake']):
      # run succeeded as expected
      pass

  def test_in_process(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      with temporary_dir(root_dir=self.workdir_root()) as cachedir:
        pants_run = self.run_test_compile(
          workdir, cachedir, 'examples/src/java/org/pantsbuild/example/hello/main',
          extra_args=['--no-compile-java-use-jmake', '-ldebug'], clean_all=True
        )
        self.assertIn('Attempting to call com.sun.tools.javac.api.JavacTool', pants_run.stdout_data)
        self.assertNotIn('Forking javac', pants_run.stdout_data)

  def test_log_level(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      with temporary_dir(root_dir=self.workdir_root()) as cachedir:
        target = 'testprojects/src/java/org/pantsbuild/testproject/dummies:compilation_failure_target'
        pants_run = self.run_test_compile(
          workdir, cachedir, target,
          extra_args=['--no-compile-java-use-jmake', '--no-color'], clean_all=True
        )
        self.assertIn('[warn] import sun.security.x509.X500Name;', pants_run.stdout_data)
        self.assertIn('[error]     System2.out.println("Hello World!");', pants_run.stdout_data)

  def test_unicode_source_symbol(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      with temporary_dir(root_dir=self.workdir_root()) as cachedir:
        target = 'testprojects/src/scala/org/pantsbuild/testproject/unicode/unicodedep/consumer'
        pants_run = self.run_test_compile(
          workdir, cachedir, target,
          extra_args=[
            '--compile-zinc-name-hashing',
            '--cache-compile-zinc-write-to=["{}/dummy_artifact_cache_dir"]'.format(cachedir),
          ],
          clean_all=True,
        )
        self.assert_success(pants_run)
