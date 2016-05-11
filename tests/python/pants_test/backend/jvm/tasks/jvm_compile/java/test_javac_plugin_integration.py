# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from unittest import skipIf

from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT
from pants_test.backend.jvm.tasks.missing_jvm_check import is_missing_jvm


@skipIf(is_missing_jvm('1.8'), 'no java 1.8 installation on testing machine')
class JavacPluginIntegrationTest(BaseCompileIT):
  # A target without a dep on the plugin.
  independent_tgt = 'testprojects/src/java/org/pantsbuild/testproject/publish/hello/main'

  # A target with a dep on the plugin.
  dependent_tgt = 'examples/src/java/org/pantsbuild/example/plugin:hello_plugin'

  def _do_test_plugin(self, args, compile_tgt, global_plugin):
    config = {
      'compile.zinc': {
        'javac_plugins': 'simple_javac_plugin',
        'javac_plugin_args': {
          'simple_javac_plugin': args
        }
      }
    }
    if global_plugin:
      config['java'] = {
        'compiler_plugin_deps':
          'examples/src/java/org/pantsbuild/example/plugin:simple_javac_plugin'
      }

    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir([
        'compile',
        compile_tgt,
      ],
      workdir, config)
      self.assert_success(pants_run)
      self.assertIn('SimpleJavacPlugin ran with {} args: {}'.format(
          len(args), ' '.join(args)), pants_run.stdout_data)

  def test_plugin_0_args(self):
    self._do_test_plugin([], self.independent_tgt, True)

  def test_plugin_1_arg(self):
    self._do_test_plugin(['abc'], self.independent_tgt, True)

  def test_plugin_2_args(self):
    self._do_test_plugin(['abc', 'def'], self.independent_tgt, True)

  def test_direct_dep_on_plugin(self):
    # No global plugin, but it should still run because the target depends on it.
    self._do_test_plugin([], self.dependent_tgt, False)
