# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import unittest

from pants.help.help_formatter import HelpFormatter
from pants.help.help_info_extracter import OptionHelpInfo


class OptionHelpFormatterTest(unittest.TestCase):
  def format_help_for_foo(self, **kwargs):
    ohi = OptionHelpInfo(registering_class=type(None), display_args=['--foo'],
                         scoped_cmd_line_args=['--foo'], unscoped_cmd_line_args=['--foo'],
                         typ=bool, default=None, help='help for foo',
                         deprecated_message=None, removal_version=None, removal_hint=None,
                         choices=None)
    ohi = ohi._replace(**kwargs)
    lines = HelpFormatter(scope='', show_recursive=False, show_advanced=False,
                          color=False).format_option(ohi)
    self.assertEqual(len(lines), 2)
    self.assertIn('help for foo', lines[1])
    return lines[0]

  def test_format_help(self):
    line = self.format_help_for_foo(default='MYDEFAULT')
    self.assertEqual('--foo (default: MYDEFAULT)', line)

  def test_suppress_advanced(self):
    args = ['--foo']
    kwargs = {'advanced': True}
    lines = HelpFormatter(scope='', show_recursive=False, show_advanced=False,
                          color=False).format_options('', '', [(args, kwargs)])
    self.assertEqual(0, len(lines))
    lines = HelpFormatter(scope='', show_recursive=True, show_advanced=True,
                          color=False).format_options('', '', [(args, kwargs)])
    print(lines)
    self.assertEqual(5, len(lines))

  def test_format_help_choices(self):
    line = self.format_help_for_foo(typ=str, default='kiwi', choices='apple, banana, kiwi')
    self.assertEqual('--foo (one of: [apple, banana, kiwi] default: kiwi)', line)
