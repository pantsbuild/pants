# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os.path

from pants.backend.core.tasks.targets_help import TargetsHelp
from pants_test.tasks.test_base import ConsoleTaskTest


class TargetsHelpTest(ConsoleTaskTest):
  @classmethod
  def task_type(cls):
    return TargetsHelp

  # The build_file_parser doesn't have any symbols defined; all we have
  # are the PREDEFS, things like "dependencies: Old name for 'target'"

  def test_list_all(self):
    output = '\n'.join(self.execute_console_task())
    self.assertIn('Old name for', output)

  def test_bad_details(self):
    self.assert_console_output('No such symbol: invalid',
                               args=['--test-details=invalid'])
