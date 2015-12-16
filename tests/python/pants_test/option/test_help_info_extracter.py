# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from mock import mock

from pants.help.help_info_extracter import HelpInfoExtracter
from pants.option.custom_types import dict_option, list_option


class HelpInfoExtracterTest(unittest.TestCase):
  def test_global_scope(self):
    def do_test(args, kwargs, expected_display_args, expected_scoped_cmd_line_args):
      # The scoped and unscoped args are the same in global scope.
      expected_unscoped_cmd_line_args = expected_scoped_cmd_line_args
      ohi = HelpInfoExtracter('').get_option_help_info(args, kwargs)
      self.assertListEqual(expected_display_args, ohi.display_args)
      self.assertListEqual(expected_scoped_cmd_line_args, ohi.scoped_cmd_line_args)
      self.assertListEqual(expected_unscoped_cmd_line_args, ohi.unscoped_cmd_line_args)

    do_test(['-f'], {'action': 'store_true'}, ['-f'], ['-f'])
    do_test(['--foo'], {'action': 'store_true'}, ['--[no-]foo'], ['--foo', '--no-foo'])
    do_test(['--foo'], {'action': 'store_false'}, ['--[no-]foo'], ['--foo', '--no-foo'])
    do_test(['-f', '--foo'], {'action': 'store_true'}, ['-f', '--[no-]foo'],
                                                       ['-f', '--foo', '--no-foo'])

    do_test(['--foo'], {}, ['--foo=<str>'], ['--foo'])
    do_test(['--foo'], {'metavar': 'xx'}, ['--foo=xx'], ['--foo'])
    do_test(['--foo'], {'type': int}, ['--foo=<int>'], ['--foo'])
    do_test(['--foo'], {'type': list_option}, ['--foo="[\'str1\',\'str2\',...]"'], ['--foo'])
    do_test(['--foo'], {'type': dict_option}, ['--foo="{\'key1\':val1,\'key2\':val2,...}"'],
                                            ['--foo'])
    do_test(['--foo'], {'action': 'append'},
            ['--foo=<str> (--foo=<str>) ...'], ['--foo'])

    do_test(['--foo', '--bar'], {}, ['--foo=<str>', '--bar=<str>'], ['--foo', '--bar'])

  def test_non_global_scope(self):
    def do_test(args, kwargs, expected_display_args, expected_scoped_cmd_line_args,
                expected_unscoped_cmd_line_args):
      ohi = HelpInfoExtracter('bar.baz').get_option_help_info(args, kwargs)
      self.assertListEqual(expected_display_args, ohi.display_args)
      self.assertListEqual(expected_scoped_cmd_line_args, ohi.scoped_cmd_line_args)
      self.assertListEqual(expected_unscoped_cmd_line_args, ohi.unscoped_cmd_line_args)
    do_test(['-f'], {'action': 'store_true'}, ['--bar-baz-f'], ['--bar-baz-f'], ['-f'])
    do_test(['--foo'], {'action': 'store_true'}, ['--[no-]bar-baz-foo'],
            ['--bar-baz-foo', '--no-bar-baz-foo'], ['--foo', '--no-foo'])
    do_test(['--foo'], {'action': 'store_false'}, ['--[no-]bar-baz-foo'],
            ['--bar-baz-foo', '--no-bar-baz-foo'], ['--foo', '--no-foo'])

  def test_default(self):
    r = lambda value: mock.Mock(value=value)

    def do_test(args, kwargs, expected_default):
      ohi = HelpInfoExtracter('').get_option_help_info(args, kwargs)
      self.assertEqual(expected_default, ohi.default)

    do_test(['--foo'], {'action': 'store_true'}, 'False')
    do_test(['--foo'], {'action': 'store_true', 'default': r(True)}, 'True')
    do_test(['--foo'], {'action': 'store_false'}, 'True')
    do_test(['--foo'], {'action': 'store_false', 'default': r(False)}, 'False')
    do_test(['--foo'], {}, 'None')
    do_test(['--foo'], {'type': int}, 'None')
    do_test(['--foo'], {'type': int, 'default': r(42)}, '42')
    # TODO: Change these if we change the defaults to empty lists/dicts.
    do_test(['--foo'], {'type': list_option}, 'None')
    do_test(['--foo'], {'type': dict_option}, 'None')
    do_test(['--foo'], {'action': 'append'}, 'None')

  def test_deprecated(self):
    kwargs = {'deprecated_version': '999.99.9', 'deprecated_hint': 'do not use this'}
    ohi = HelpInfoExtracter('').get_option_help_info([], kwargs)
    self.assertEquals('999.99.9', ohi.deprecated_version)
    self.assertEquals('do not use this', ohi.deprecated_hint)
    self.assertIsNotNone(ohi.deprecated_message)

  def test_fromfile(self):
    ohi = HelpInfoExtracter('').get_option_help_info([], {})
    self.assertFalse(ohi.fromfile)

    kwargs = {'fromfile': False}
    ohi = HelpInfoExtracter('').get_option_help_info([], kwargs)
    self.assertFalse(ohi.fromfile)

    kwargs = {'fromfile': True}
    ohi = HelpInfoExtracter('').get_option_help_info([], kwargs)
    self.assertTrue(ohi.fromfile)

  def test_grouping(self):
    def do_test(kwargs, expected_basic=False, expected_recursive=False, expected_advanced=False):
      def exp_to_len(exp):
        return int(exp)  # True -> 1, False -> 0.

      oshi = HelpInfoExtracter('').get_option_scope_help_info([([], kwargs)])
      self.assertEquals(exp_to_len(expected_basic), len(oshi.basic))
      self.assertEquals(exp_to_len(expected_recursive), len(oshi.recursive))
      self.assertEquals(exp_to_len(expected_advanced), len(oshi.advanced))

    do_test({}, expected_basic=True)
    do_test({'advanced': False}, expected_basic=True)
    do_test({'advanced': True}, expected_advanced=True)
    do_test({'recursive': True}, expected_recursive=True)
    do_test({'recursive': True, 'recursive_root': True}, expected_basic=True)
    do_test({'advanced': True, 'recursive': True}, expected_advanced=True)
    do_test({'advanced': True, 'recursive': True, 'recursive_root': True}, expected_advanced=True)
