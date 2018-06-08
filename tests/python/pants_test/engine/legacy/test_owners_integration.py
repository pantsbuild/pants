# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ListOwnersIntegrationTest(PantsRunIntegrationTest):
  def test_owner_of_success(self):
    pants_run = self.do_command('--owner-of=testprojects/tests/python/pants/dummies/test_pass.py',
                                'list',
                                success=True)
    self.assertEquals(
      pants_run.stdout_data.strip(),
      'testprojects/tests/python/pants/dummies:passing_target'
    )

  def test_owner_list_not_owned(self):
    pants_run = self.do_command('--owner-of=testprojects/tests/python/pants/dummies/test_nonexistent.py',
                                'list',
                                success=True)
    self.assertIn('WARNING: No targets were matched in', pants_run.stderr_data)