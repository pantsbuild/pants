# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.testutils.py2_compat import assertRegex


class ListIntegrationTest(PantsRunIntegrationTest):

  def get_target_set(self, std_out):
    return sorted([l for l in std_out.split('\n') if l])

  def run_engine_list(self, success, *args):
    return self.get_target_set(self.do_command(*args, success=success).stdout_data)

  def test_list_all(self):
    pants_run = self.do_command('list', '::', success=True)
    self.assertGreater(len(pants_run.stdout_data.strip().split()), 1)

  def test_list_none(self):
    pants_run = self.do_command('list', success=True)
    self.assertIn('WARNING: No targets were matched in', pants_run.stderr_data)

  def test_list_invalid_dir(self):
    pants_run = self.do_command('list', 'abcde::', success=False)
    self.assertIn('AddressLookupError', pants_run.stderr_data)

  def test_list_nested_function_scopes(self):
    pants_run = self.do_command('list',
                                'testprojects/tests/python/pants/build_parsing::',
                                success=True)
    self.assertEqual(
      pants_run.stdout_data.strip(),
      'testprojects/tests/python/pants/build_parsing:test-nested-variable-access-in-function-call'
    )

  def test_list_parse_java_targets(self):
    pants_run = self.do_command('list',
                                'testprojects/tests/java/org/pantsbuild/build_parsing::',
                                success=True)
    assertRegex(self,
      pants_run.stdout_data,
      r'testprojects/tests/java/org/pantsbuild/build_parsing:trailing_glob_doublestar'
    )
