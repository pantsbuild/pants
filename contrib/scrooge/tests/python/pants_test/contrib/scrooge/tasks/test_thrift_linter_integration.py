# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from functools import wraps

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ThriftLinterTest(PantsRunIntegrationTest):

  lint_error_token = "LINT-ERROR"
  thrift_folder_root = 'contrib/scrooge/tests/thrift/org/pantsbuild/contrib/scrooge/thrift_linter'

  @classmethod
  def hermetic(cls):
    return True

  @classmethod
  def thrift_test_target(cls, name):
    return '{}:{}'.format(cls.thrift_folder_root, name)

  def rename_build_file(func):
    """This decorator implements the TEST_BUILD pattern.

    Because these tests use files that intentionally should fail linting, the goal `./pants lint ::`
    we use in CI would complain about these files. To avoid this, we rename BUILD to TEST_BUILD.

    However, these tests require us to temporarily rename TEST_BUILD back to BUILD. """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
      with self.file_renamed(self.thrift_folder_root, test_name='TEST_BUILD', real_name='BUILD'):
        func(self, *args, **kwargs)
    return wrapper

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

  @rename_build_file
  def test_good(self):
    # thrift-linter should pass without warnings with correct thrift files.
    cmd = ['lint.thrift', self.thrift_test_target('good-thrift')]
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)
    self.assertNotIn(self.lint_error_token, pants_run.stdout_data)

  @rename_build_file
  def test_bad_default(self):
    # thrift-linter fails on linter errors.
    cmd = ['lint.thrift', self.thrift_test_target('bad-thrift-default')]
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)
    self.assertIn(self.lint_error_token, pants_run.stdout_data)

  @rename_build_file
  def test_bad_strict(self):
    # thrift-linter fails on linter errors (BUILD target defines thrift_linter_strict=True)
    cmd = ['lint.thrift', self.thrift_test_target('bad-thrift-strict')]
    pants_run = self.run_pants(cmd)
    self.assert_failure(pants_run)
    self.assertIn(self.lint_error_token, pants_run.stdout_data)

  @rename_build_file
  def test_bad_non_strict(self):
    # thrift-linter fails on linter errors (BUILD target defines thrift_linter_strict=False)
    cmd = ['lint.thrift', self.thrift_test_target('bad-thrift-non-strict')]
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)
    self.assertIn(self.lint_error_token, pants_run.stdout_data)

  @rename_build_file
  def test_bad_default_override(self):
    # thrift-linter fails with command line flag overriding the BUILD section.
    cmd = ['lint.thrift', '--strict', self.thrift_test_target('bad-thrift-default')]
    pants_run = self.run_pants(cmd)
    self.assert_failure(pants_run)
    self.assertIn(self.lint_error_token, pants_run.stdout_data)

  @rename_build_file
  def test_multiple_bad_strict_override(self):
    # Using -q to make sure bad thrift files are in the final exception messages.
    target_a = self.thrift_test_target('bad-thrift-strict')
    target_b = self.thrift_test_target('bad-thrift-strict2')
    cmd = ['-q',
           'lint.thrift',
           '--strict',
           target_a,
           target_b,
           ]
    pants_run = self.run_pants(cmd)
    self.assert_failure(pants_run)
    self.assertIn('bad-strict2.thrift', pants_run.stdout_data)
    self.assertIn('bad-strict.thrift', pants_run.stdout_data)
    self.assertIn(target_a, pants_run.stdout_data)
    self.assertIn(target_b, pants_run.stdout_data)

  @rename_build_file
  def test_bad_strict_override(self):
    # thrift-linter passes with non-strict command line flag overriding the BUILD section.
    cmd = ['lint.thrift', '--no-strict', self.thrift_test_target('bad-thrift-strict')]
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)
    self.assertIn(self.lint_error_token, pants_run.stdout_data)

  @rename_build_file
  def test_bad_non_strict_override(self):
    # thrift-linter fails with command line flag overriding the BUILD section.
    cmd = ['lint.thrift', '--strict', self.thrift_test_target('bad-thrift-non-strict')]
    pants_run = self.run_pants(cmd)
    self.assert_failure(pants_run)
    self.assertIn(self.lint_error_token, pants_run.stdout_data)

  @rename_build_file
  def test_bad_pants_ini_strict(self):
    # thrift-linter fails if pants.ini has a thrift-linter:strict=True setting.
    cmd = ['lint.thrift', self.thrift_test_target('bad-thrift-default')]
    pants_ini_config = {'lint.thrift': {'strict': True}}
    pants_run = self.run_pants(cmd, config=pants_ini_config)
    self.assert_failure(pants_run)
    self.assertIn(self.lint_error_token, pants_run.stdout_data)

  @rename_build_file
  def test_bad_pants_ini_strict_overridden(self):
    # thrift-linter passes if pants.ini has a thrift-linter:strict=True setting and
    # a command line non-strict flag is passed.
    cmd = ['lint.thrift', '--no-strict', self.thrift_test_target('bad-thrift-default')]
    pants_ini_config = {'lint.thrift': {'strict': True}}
    pants_run = self.run_pants(cmd, config=pants_ini_config)
    self.assert_success(pants_run)
    self.assertIn(self.lint_error_token, pants_run.stdout_data)
