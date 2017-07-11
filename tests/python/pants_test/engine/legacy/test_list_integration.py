# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ListIntegrationTest(PantsRunIntegrationTest):

  def get_target_set(self, std_out):
    return sorted([l for l in std_out.split('\n') if l])

  def run_engine_list(self, success, *args):
    return self.get_target_set(self.do_command(*args, success=success, enable_v2_engine=True).stdout_data)

  def run_regular_list(self, success, *args):
    return self.get_target_set(self.do_command(*args, success=success, enable_v2_engine=False).stdout_data)

  def assert_list_new_equals_old(self, success, spec):
    args = ['-q', 'list'] + spec
    self.assertEqual(
      self.run_regular_list(success, *args),
      self.run_engine_list(success, *args),
    )

  def test_list_single(self):
    self.assert_list_new_equals_old(True, ['::'])

  def test_list_multiple(self):
    self.assert_list_new_equals_old(
      True,
      ['3rdparty::', 'examples/src/::', 'testprojects/tests/::', 'contrib/go/examples/3rdparty::']
    )

  def test_list_all(self):
    pants_run = self.do_command('list', '::', success=True, enable_v2_engine=True)
    self.assertGreater(len(pants_run.stdout_data.strip().split()), 1)

  def test_list_none(self):
    pants_run = self.do_command('list', success=True, enable_v2_engine=True)
    self.assertEqual(len(pants_run.stdout_data.strip().split()), 0)

  @unittest.skip('Skipped to expedite landing #3821.')
  def test_list_invalid_dir(self):
    pants_run = self.do_command('list', 'abcde::', success=False, enable_v2_engine=True)
    self.assertIn('InvalidCommandLineSpecError', pants_run.stderr_data)

  def test_list_nested_function_scopes(self):
    pants_run = self.do_command('list',
                                'testprojects/tests/python/pants/build_parsing::',
                                success=True,
                                enable_v2_engine=True)
    self.assertEquals(
      pants_run.stdout_data.strip(),
      'testprojects/tests/python/pants/build_parsing:test-nested-variable-access-in-function-call'
    )

  def test_list_parse_java_targets(self):
    pants_run = self.do_command('list',
                                'testprojects/tests/java/org/pantsbuild/build_parsing::',
                                success=True,
                                enable_v2_engine=True)
    self.assertRegexpMatches(
      pants_run.stdout_data,
      r'testprojects/tests/java/org/pantsbuild/build_parsing:trailing_glob_doublestar'
    )
