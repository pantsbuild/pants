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
    pants_run = self.run_pants([
      '--build-file-imports=error',
      'run',
      'testprojects/src/python/build_file_imports_module:hello',
    ], print_exception_stacktrace=False)
    self.assert_failure(pants_run)
    self.assertIn('testprojects/src/python/build_file_imports_module/BUILD', pants_run.stderr_data)
    self.assertIn('import os.path', pants_run.stderr_data)

  def test_warn_module_import(self):
    pants_run = self.run_pants([
      '--build-file-imports=warn',
      'run',
      'testprojects/src/python/build_file_imports_module:hello',
    ])
    self.assert_success(pants_run)
    self.assertIn('Hello\n', pants_run.stdout_data)
    self.assertIn('directory testprojects/src/python/build_file_imports_module', pants_run.stderr_data)
    self.assertIn('import os.path', pants_run.stderr_data)

  def test_banned_function_import(self):
    pants_run = self.run_pants([
      '--build-file-imports=error',
      'run',
      'testprojects/src/python/build_file_imports_function:hello',
    ], print_exception_stacktrace=False)
    self.assert_failure(pants_run)
    self.assertIn('testprojects/src/python/build_file_imports_function/BUILD', pants_run.stderr_data)
    self.assertIn('import os.path', pants_run.stderr_data)

  def test_warn_function_import(self):
    pants_run = self.run_pants([
      '--build-file-imports=warn',
      'run',
      'testprojects/src/python/build_file_imports_function:hello',
    ])
    self.assert_success(pants_run)
    self.assertIn('Hello\n', pants_run.stdout_data)
    self.assertIn('directory testprojects/src/python/build_file_imports_function', pants_run.stderr_data)
    self.assertIn('import os.path', pants_run.stderr_data)

  def test_allowed_module_import(self):
    pants_run = self.run_pants([
      '--build-file-imports=allow',
      'run',
      'testprojects/src/python/build_file_imports_module:hello',
    ])
    self.assert_success(pants_run)
    self.assertIn('Hello\n', pants_run.stdout_data)

  def test_allowed_function_import(self):
    pants_run = self.run_pants([
      '--build-file-imports=allow',
      'run',
      'testprojects/src/python/build_file_imports_function:hello',
    ])
    self.assert_success(pants_run)
    self.assertIn('Hello\n', pants_run.stdout_data)
