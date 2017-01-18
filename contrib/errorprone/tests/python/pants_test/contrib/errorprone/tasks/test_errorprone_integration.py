# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ErrorProneTest(PantsRunIntegrationTest):

  @classmethod
  def hermetic(cls):
    return True

  def run_pants(self, command, config=None, stdin_data=None, extra_env=None, **kwargs):
    full_config = {
      'GLOBAL': {
        'pythonpath': ["%(buildroot)s/contrib/errorprone/src/python"],
        'backend_packages': ["pants.backend.codegen", "pants.backend.jvm", "pants.contrib.errorprone"]
      }
    }
    if config:
      for scope, scoped_cfgs in config.items():
        updated = full_config.get(scope, {})
        updated.update(scoped_cfgs)
        full_config[scope] = updated
    return super(ErrorProneTest, self).run_pants(command, full_config, stdin_data, extra_env, **kwargs)

  def test_no_warnings(self):
    cmd = ['compile', 'contrib/errorprone/tests/java/org/pantsbuild/contrib/errorprone:none']
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)
    self.assertNotIn('warning:', pants_run.stdout_data)
    self.assertNotIn('error:', pants_run.stdout_data)

  def test_empty_source_file(self):
    cmd = ['compile', 'contrib/errorprone/tests/java/org/pantsbuild/contrib/errorprone:empty']
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)
    self.assertNotIn('warning:', pants_run.stdout_data)
    self.assertNotIn('error:', pants_run.stdout_data)

  def test_warning(self):
    cmd = ['compile', 'contrib/errorprone/tests/java/org/pantsbuild/contrib/errorprone:warning']
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)
    self.assertIn('warning: [ReferenceEquality] Comparison using reference equality instead of value equality', pants_run.stdout_data)
    self.assertIn('(see http://errorprone.info/bugpattern/ReferenceEquality)', pants_run.stdout_data)
    self.assertNotIn('error:', pants_run.stdout_data)
    self.assertIn('1 warning', pants_run.stdout_data)

  def test_error(self):
    cmd = ['compile', 'contrib/errorprone/tests/java/org/pantsbuild/contrib/errorprone:error']
    pants_run = self.run_pants(cmd)
    self.assert_failure(pants_run)
    self.assertIn('error: [ArrayToString] Calling toString on an array does not provide useful information', pants_run.stdout_data)
    self.assertIn('(see http://errorprone.info/bugpattern/ArrayToString)', pants_run.stdout_data)
    self.assertNotIn('warning:', pants_run.stdout_data)
    self.assertIn('1 error', pants_run.stdout_data)

  def test_warning_gets_cached(self):
    with self.temporary_cachedir() as cache:
      args = [
        'compile',
        '--cache-write',
        "--cache-write-to=['{}']".format(cache),
        '--cache-read',
        "--cache-read-from=['{}']".format(cache),
        'contrib/errorprone/tests/java/org/pantsbuild/contrib/errorprone:warning',
      ]

      pants_run = self.run_pants(args)
      self.assert_success(pants_run)
      self.assertIn('[errorprone]', pants_run.stdout_data)
      self.assertIn('No cached artifacts', pants_run.stdout_data)
      self.assertIn('1 warning', pants_run.stdout_data)

      pants_run = self.run_pants(args)
      self.assert_success(pants_run)
      self.assertIn('[errorprone]', pants_run.stdout_data)
      self.assertIn('Using cached artifacts', pants_run.stdout_data)
      self.assertNotIn('No cached artifacts', pants_run.stdout_data)
      self.assertNotIn('1 warning', pants_run.stdout_data)

  def test_error_does_not_get_cached(self):
    with self.temporary_cachedir() as cache:
      args = [
        'compile',
        '--cache-write',
        "--cache-write-to=['{}']".format(cache),
        '--cache-read',
        "--cache-read-from=['{}']".format(cache),
        'contrib/errorprone/tests/java/org/pantsbuild/contrib/errorprone:error',
      ]

      pants_run = self.run_pants(args)
      self.assert_failure(pants_run)
      self.assertIn('[errorprone]', pants_run.stdout_data)
      self.assertIn('No cached artifacts', pants_run.stdout_data)
      self.assertIn('1 error', pants_run.stdout_data)

      pants_run = self.run_pants(args)
      self.assert_failure(pants_run)
      self.assertIn('[errorprone]', pants_run.stdout_data)
      self.assertIn('Using cached artifacts', pants_run.stdout_data)
      self.assertIn('1 error', pants_run.stdout_data)
