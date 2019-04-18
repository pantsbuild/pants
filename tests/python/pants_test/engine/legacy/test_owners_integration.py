# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest, ensure_daemon


class ListOwnersIntegrationTest(PantsRunIntegrationTest):
  @ensure_daemon
  def test_owner_of_success(self):
    pants_run = self.do_command('--owner-of=testprojects/tests/python/pants/dummies/test_pass.py',
                                'list',
                                success=True)
    self.assertEqual(
      pants_run.stdout_data.strip(),
      'testprojects/tests/python/pants/dummies:passing_target'
    )

  def test_owner_list_not_owned(self):
    pants_run = self.do_command('--owner-of=testprojects/tests/python/pants/dummies/test_nonexistent.py',
                                'list',
                                success=True)
    self.assertIn('WARNING: No targets were matched in', pants_run.stderr_data)

  def test_owner_list_two_target_specs(self):
    # Test that any of these combinations fail with the same error message.
    expected_error = ('Multiple target selection methods provided. Please use only one of '
                      '--changed-*, --owner-of, or target specs')
    pants_run_1 = self.do_command('--owner-of=testprojects/tests/python/pants/dummies/test_pass.py',
                                  '--changed-parent=master',
                                  'list',
                                  success=False)
    self.assertIn(expected_error, pants_run_1.stderr_data)

    pants_run_2 = self.do_command('--owner-of=testprojects/tests/python/pants/dummies/test_pass.py',
                                  'list',
                                  'testprojects/tests/python/pants/dummies:passing_target',
                                  success=False)
    self.assertIn(expected_error, pants_run_2.stderr_data)

    pants_run_3 = self.do_command('--changed-parent=master',
                                  'list',
                                  'testprojects/tests/python/pants/dummies:passing_target',
                                  success=False)
    self.assertIn(expected_error, pants_run_3.stderr_data)

  def test_owner_list_repeated_directory_separator(self):
    pants_run = self.do_command('--owner-of=testprojects/tests/python/pants/dummies//test_pass.py',
                                'list',
                                success=True)
    self.assertEqual(
      set([
        'testprojects/tests/python/pants/dummies:passing_target',
        'testprojects/tests/python/pants:secondary_source_file_owner'
      ]),
      set(pants_run.stdout_data.splitlines()),
    )
