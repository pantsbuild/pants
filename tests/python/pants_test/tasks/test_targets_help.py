# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os.path

from pants.base.build_environment import get_buildroot
from pants.base.source_root import SourceRoot
from pants.base.target import Target
from pants.tasks.targets_help import TargetsHelp
from pants_test.tasks.test_base import ConsoleTaskTest


class TargetsHelpTest(ConsoleTaskTest):

  @classmethod
  def task_type(cls):
    return TargetsHelp

  @classmethod
  def setUpClass(cls):
    super(TargetsHelpTest, cls).setUpClass()
    SourceRoot.register(os.path.join(get_buildroot(), 'fakeroot'), TargetsHelpTest.MyTarget)

  def test_list_installed_targets(self):
    self.assert_console_output(
      TargetsHelp.INSTALLED_TARGETS_HEADER,
      '  %s: %s' % ('my_target'.rjust(TargetsHelp.MAX_ALIAS_LEN),
                    TargetsHelpTest.MyTarget.__doc__.split('\n')[0]))

  def test_get_details(self):
    self.assert_console_output(
      TargetsHelp.DETAILS_HEADER.substitute(
        name='my_target', desc=TargetsHelpTest.MyTarget.__doc__),
      '  name: The name of this target.',
      '   foo: Another argument.  (default: None)',
      args=['--test-details=my_target'])

  class MyTarget(Target):
    """One-line description of the target."""
    def __init__(self, name, foo=None):
      """
      :param name: The name of this target.
      :param string foo: Another argument.
      """
      Target.__init__(self, name)
