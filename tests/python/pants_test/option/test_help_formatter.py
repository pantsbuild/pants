# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.help.help_formatter import HelpFormatter
from pants.help.help_info_extracter import OptionHelpInfo


class OptionHelpFormatterTest(unittest.TestCase):
  def test_format_help(self):
    ohi = OptionHelpInfo(registering_class=type(None), display_args=['--foo'],
                         scoped_cmd_line_args=['--foo'], unscoped_cmd_line_args=['--foo'],
                         type=bool, default='MYDEFAULT', help='help for foo',
                         deprecated_version=None, deprecated_message=None, deprecated_hint=None)

    lines = HelpFormatter(scope='', show_recursive=False, show_advanced=False,
                          color=False).format_option(ohi)
    self.assertEquals(len(lines), 2)
    self.assertEquals('--foo (default: MYDEFAULT)', lines[0])
    self.assertIn('help for foo', lines[1])

  def test_suppress_advanced(self):
    args = ['--foo']
    kwargs = {'advanced': True}
    lines = HelpFormatter(scope='', show_recursive=False, show_advanced=False,
                          color=False).format_options('', '', [(args, kwargs)])
    self.assertEquals(0, len(lines))
    lines = HelpFormatter(scope='', show_recursive=True, show_advanced=True,
                          color=False).format_options('', '', [(args, kwargs)])
    print(lines)
    self.assertEquals(5, len(lines))
