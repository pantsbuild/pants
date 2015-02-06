# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os.path

from pants.backend.core.tasks.targets_help import TargetsHelp
from pants_test.tasks.test_base import ConsoleTaskTest


# The build_file_parser doesn't have any symbols defined; all we have
# are the PREDEFS, things like "dependencies: Old name for 'target'".
# But we can make sure they don't blow up.
class TargetsHelpTest(ConsoleTaskTest):
  @classmethod
  def task_type(cls):
    return TargetsHelp

  def test_list_all(self):
    output = '\n'.join(self.execute_console_task())
    self.assertIn('Old name for', output)

  def test_ok_details(self):
    # If something has an entry in predefs, we should render it
    # Assumes that we have an entry for 'egg' in PREDEFS
    output = '\n'.join(self.execute_console_task(args=['--test-details=egg']))
    self.assertIn('In older Pants', output)

  def test_bad_details(self):
    self.assert_console_output('\nNo such symbol: invalid\n',
                               args=['--test-details=invalid'])
