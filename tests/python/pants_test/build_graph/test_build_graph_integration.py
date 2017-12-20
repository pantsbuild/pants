# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class BuildGraphIntegrationTest(PantsRunIntegrationTest):

  def test_cycle(self):
    prefix = 'testprojects/src/java/org/pantsbuild/testproject'
    with self.file_renamed(os.path.join(prefix, 'cycle1'), 'TEST_BUILD', 'BUILD'):
      with self.file_renamed(os.path.join(prefix, 'cycle2'), 'TEST_BUILD', 'BUILD'):
        pants_run = self.run_pants(['compile', os.path.join(prefix, 'cycle1')])
        self.assert_failure(pants_run)
        self.assertIn('Cycle detected', pants_run.stderr_data)

  def test_banned_module_import(self):
    self.banned_import('testprojects/src/python/build_file_imports_module')

  def test_banned_function_import(self):
    self.banned_import('testprojects/src/python/build_file_imports_function')

  def banned_import(self, dir):
    with self.file_renamed(dir, 'TEST_BUILD', 'BUILD'):
      pants_run = self.run_pants([
        '--build-file-imports=error',
        'run',
        '{}:hello'.format(dir),
      ], print_exception_stacktrace=False)
      self.assert_failure(pants_run)
      self.assertIn('{}/BUILD'.format(dir), pants_run.stderr_data)
      self.assertIn('os.path', pants_run.stderr_data)

  def test_warn_module_import(self):
    self.warn_import('testprojects/src/python/build_file_imports_module')

  def test_warn_function_import(self):
    self.warn_import('testprojects/src/python/build_file_imports_function')

  def warn_import(self, dir):
    with self.file_renamed(dir, 'TEST_BUILD', 'BUILD'):
      pants_run = self.run_pants([
        '--build-file-imports=warn',
        'run',
        '{}:hello'.format(dir),
      ])
      self.assert_success(pants_run)
      self.assertIn('Hello\n', pants_run.stdout_data)
      self.assertIn('{}/BUILD'.format(dir), pants_run.stderr_data)
      self.assertIn('os.path', pants_run.stderr_data)

  def test_allowed_module_import(self):
    self.allowed_import('testprojects/src/python/build_file_imports_module')

  def test_allowed_function_import(self):
    self.allowed_import('testprojects/src/python/build_file_imports_function')

  def allowed_import(self, dir):
    with self.file_renamed(dir, 'TEST_BUILD', 'BUILD'):
      pants_run = self.run_pants([
        '--build-file-imports=allow',
        'run',
        '{}:hello'.format(dir),
      ])
    self.assert_success(pants_run)
    self.assertIn('Hello\n', pants_run.stdout_data)
