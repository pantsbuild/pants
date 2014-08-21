# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os.path

from pants.base.build_environment import get_buildroot
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.source_root import SourceRoot
from pants.base.target import Target
from pants.backend.core.tasks.targets_help import TargetsHelp
from pants_test.tasks.test_base import ConsoleTaskTest


class TargetsHelpTest(ConsoleTaskTest):

  MY_TARGET_ALIAS = 'my_target'

  @classmethod
  def task_type(cls):
    return TargetsHelp

  @property
  def alias_groups(self):
    return BuildFileAliases.create(
      targets={TargetsHelpTest.MY_TARGET_ALIAS: TargetsHelpTest.MyTarget})

  def setUp(self):
    super(TargetsHelpTest, self).setUp()
    SourceRoot.register(os.path.join(get_buildroot(), 'fakeroot'), TargetsHelpTest.MyTarget)

  def test_list_installed_targets(self):
    self.assert_console_output(
      TargetsHelp.INSTALLED_TARGETS_HEADER,
      '  %s: %s' % (TargetsHelpTest.MY_TARGET_ALIAS.rjust(len(TargetsHelpTest.MY_TARGET_ALIAS)),
                    TargetsHelpTest.MyTarget.__doc__.split('\n')[0]))

  def test_get_details(self):
    self.assert_console_output(
      TargetsHelp.DETAILS_HEADER.substitute(
        name=TargetsHelpTest.MY_TARGET_ALIAS, desc=TargetsHelpTest.MyTarget.__doc__),
      '  name: The name of this target.',
      '   foo: Another argument.  (default: None)',
      args=['--test-details={0}'.format(TargetsHelpTest.MY_TARGET_ALIAS)])

  def test_invalid_target_alias_cli_option_cause_raise(self):
    self.assert_console_raises(
      ValueError,
      args=['--test-details=invalid'])


  class MyTarget(Target):
    """One-line description of the target."""
    def __init__(self, name, foo=None):
      """
      :param name: The name of this target.
      :param string foo: Another argument.
      """
      Target.__init__(self, name)
