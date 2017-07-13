# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ThriftLinterTest(PantsRunIntegrationTest):

  lint_warn_token = "LINT-WARN"
  lint_error_token = "LINT-ERROR"

  @classmethod
  def hermetic(cls):
    return True

  def run_pants(self, command, config=None, stdin_data=None, extra_env=None, **kwargs):
    full_config = {
      'GLOBAL': {
        'pythonpath': ["%(buildroot)s/contrib/scrooge/src/python"],
        'backend_packages': ["pants.backend.codegen", "pants.backend.jvm", "pants.contrib.scrooge"]
      },
    }
    if config:
      for scope, scoped_cfgs in config.items():
        updated = full_config.get(scope, {})
        updated.update(scoped_cfgs)
        full_config[scope] = updated
    return super(ThriftLinterTest, self).run_pants(command, full_config, stdin_data, extra_env,
                                                   **kwargs)

  @staticmethod
  def thrift_test_target(name):
    return 'contrib/scrooge/tests/thrift/org/pantsbuild/contrib/scrooge/thrift_linter:' + name

  def test_good(self):
    # thrift-linter should pass without warnings with correct thrift files.
    cmd = ['lint.thrift-linter', self.thrift_test_target('good')]
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)
    self.assertNotIn(self.lint_error_token, pants_run.stdout_data)

  def test_skip_skips_execution(self):
    cmd = ['lint.thrift-linter', '--skip', self.thrift_test_target('error-strict')]
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)
    self.assertNotIn(self.lint_error_token, pants_run.stdout_data)

  def test_bad_default(self):
    # thrift-linter fails on linter errors.
    cmd = ['lint.thrift-linter', self.thrift_test_target('error-default')]
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)
    self.assertIn(self.lint_error_token, pants_run.stdout_data)

  def test_bad_strict(self):
    # thrift-linter fails on linter errors (BUILD target defines thrift_linter_strict=True)
    cmd = ['lint.thrift-linter', self.thrift_test_target('error-strict')]
    pants_run = self.run_pants(cmd)
    self.assert_failure(pants_run)
    self.assertIn(self.lint_error_token, pants_run.stdout_data)

  def test_bad_non_strict(self):
    # thrift-linter fails on linter errors (BUILD target defines thrift_linter_strict=False)
    cmd = ['lint.thrift-linter', self.thrift_test_target('error-non-strict')]
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)
    self.assertIn(self.lint_error_token, pants_run.stdout_data)

  def test_bad_default_override(self):
    # thrift-linter fails with command line flag overriding the BUILD section.
    cmd = ['lint.thrift-linter', '--strict', self.thrift_test_target('error-default')]
    pants_run = self.run_pants(cmd)
    self.assert_failure(pants_run)
    self.assertIn(self.lint_error_token, pants_run.stdout_data)

  def test_multiple_bad_strict_override(self):
    # Using -q to make sure bad thrift files are in the final exception messages.
    target_a = self.thrift_test_target('error-strict')
    target_b = self.thrift_test_target('error2-strict')
    cmd = ['-q',
           'lint.thrift-linter',
           '--strict',
           target_a,
           target_b,
           ]
    pants_run = self.run_pants(cmd)
    self.assert_failure(pants_run)
    self.assertIn('error.thrift', pants_run.stdout_data)
    self.assertIn('error2.thrift', pants_run.stdout_data)
    self.assertIn(target_a, pants_run.stdout_data)
    self.assertIn(target_b, pants_run.stdout_data)

  def test_bad_strict_override(self):
    # thrift-linter passes with non-strict command line flag overriding the BUILD section.
    cmd = ['lint.thrift-linter', '--no-strict', self.thrift_test_target('error-strict')]
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)
    self.assertIn(self.lint_error_token, pants_run.stdout_data)

  def test_bad_non_strict_override(self):
    # thrift-linter fails with command line flag overriding the BUILD section.
    cmd = ['lint.thrift-linter', '--strict', self.thrift_test_target('error-non-strict')]
    pants_run = self.run_pants(cmd)
    self.assert_failure(pants_run)
    self.assertIn(self.lint_error_token, pants_run.stdout_data)

  def test_bad_pants_ini_strict(self):
    # thrift-linter fails if pants.ini has a thrift-linter:strict=True setting.
    cmd = ['lint.thrift-linter', self.thrift_test_target('error-default')]
    pants_ini_config = {'lint.thrift-linter': {'strict': True}}
    pants_run = self.run_pants(cmd, config=pants_ini_config)
    self.assert_failure(pants_run)
    self.assertIn(self.lint_error_token, pants_run.stdout_data)

  def test_bad_pants_ini_strict_overridden(self):
    # thrift-linter passes if pants.ini has a thrift-linter:strict=True setting and
    # a command line non-strict flag is passed.
    cmd = ['lint.thrift-linter', '--no-strict', self.thrift_test_target('error-default')]
    pants_ini_config = {'lint.thrift-linter': {'strict': True}}
    pants_run = self.run_pants(cmd, config=pants_ini_config)
    self.assert_success(pants_run)
    self.assertIn(self.lint_error_token, pants_run.stdout_data)
