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
  example_dir = 'examples/src/java/org/pantsbuild/example/javac/plugin'

  def _do_test(self, expected_args, config, target):
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir(
        ['compile', '{}:{}'.format(self.example_dir, target)], workdir, config)
    self.assert_success(pants_run)
    self.assertIn('SimpleJavacPlugin ran with {} args: {}'.format(
      len(expected_args), ' '.join(expected_args)), pants_run.stdout_data)

  # Note that in the terminology of this test, "global" means specified via options for
  # all targets, and "local" means specified on an individual target.
  def _do_test_global(self, args):
    config = {
      'compile.zinc': {
        'javac_plugins': ['simple_javac_plugin'],
        'javac_plugin_args': {
          'simple_javac_plugin': args
        },
      }
    }
    # Must compile the plugin explicitly, since there's no dep.
    self._do_test(args, config, 'global')

  def _do_test_local_with_global_args(self, args):
    config = {
      'compile.zinc': {
        'javac_plugin_args': {
          'simple_javac_plugin': args
        }
      }
    } if args is not None else {}
    self._do_test(args, config, 'local_with_global_args')

  def test_global(self):
    self._do_test_global([])
    self._do_test_global(['abc'])
    self._do_test_global(['abc', 'def'])

  def test_global_with_local_args(self):
    self._do_test(['args', 'from', 'target', 'global_with_local_args'],
                  {
                    'compile.zinc': {
                      'javac_plugins': ['simple_javac_plugin'],
                    },
                  },
                  'global_with_local_args')

  def test_local_with_global_args(self):
    self._do_test_local_with_global_args([])
    self._do_test_local_with_global_args(['abc'])
    self._do_test_local_with_global_args(['abc', 'def'])

  def test_local(self):
    self._do_test(['args', 'from', 'target', 'local'], None, 'local')
