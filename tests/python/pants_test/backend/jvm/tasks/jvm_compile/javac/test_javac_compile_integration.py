# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.util.contextutil import temporary_dir
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT


class JavacCompileIntegration(BaseCompileIT):
  def test_basic_binary(self):
    with temporary_dir() as cache_dir:
      config = {
        'cache.compile.javac': {'write_to': [cache_dir]},
        'jvm-platform': {'compiler': 'javac'}
      }

      with self.temporary_workdir() as workdir:
        pants_run = self.run_pants_with_workdir(
          ['compile',
           'testprojects/src/java/org/pantsbuild/testproject/publish/hello/main:',
           ],
          workdir, config)
        self.assert_success(pants_run)

  def test_basic_binary_hermetic(self):
    with temporary_dir() as cache_dir:
      config = {
        'cache.compile.javac': {'write_to': [cache_dir]},
        'jvm-platform': {'compiler': 'javac'},
        'compile.javac': {'execution_strategy': 'hermetic'}
      }

      with self.temporary_workdir() as workdir:
        pants_run = self.run_pants_with_workdir(
          ['compile',
           'testprojects/src/java/org/pantsbuild/testproject/publish/hello/greet',
           ],
          workdir, config)
        self.assert_success(pants_run)
        path = os.path.join(
          workdir,
          'compile/javac/current/testprojects.src.java.org.pantsbuild.testproject.publish.hello.greet.greet/current',
          'classes/org/pantsbuild/testproject/publish/hello/greet/Greeting.class')
        self.assertTrue(os.path.exists(path))
