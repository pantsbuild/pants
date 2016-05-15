# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.help.help_info_extracter import HelpInfoExtracter
from pants.option.config import Config
from pants.option.global_options import GlobalOptionsRegistrar
from pants.option.option_tracker import OptionTracker
from pants.option.parser import Parser


class HelpInfoExtracterTest(unittest.TestCase):
  def test_global_scope(self):
    def do_test(args, kwargs, expected_display_args, expected_scoped_cmd_line_args):
      # The scoped and unscoped args are the same in global scope.
      expected_unscoped_cmd_line_args = expected_scoped_cmd_line_args
      ohi = HelpInfoExtracter('').get_option_help_info(args, kwargs)
      self.assertListEqual(expected_display_args, ohi.display_args)
      self.assertListEqual(expected_scoped_cmd_line_args, ohi.scoped_cmd_line_args)
      self.assertListEqual(expected_unscoped_cmd_line_args, ohi.unscoped_cmd_line_args)

    do_test(['-f'], {'type': bool }, ['-f'], ['-f'])
    do_test(['--foo'], {'type': bool }, ['--[no-]foo'], ['--foo', '--no-foo'])
    do_test(['--foo'], {'type': bool, 'implicit_value': False },
            ['--[no-]foo'], ['--foo', '--no-foo'])
    do_test(['-f', '--foo'], {'type': bool }, ['-f', '--[no-]foo'],
            ['-f', '--foo', '--no-foo'])

    do_test(['--foo'], {}, ['--foo=<str>'], ['--foo'])
    do_test(['--foo'], {'metavar': 'xx'}, ['--foo=xx'], ['--foo'])
    do_test(['--foo'], {'type': int}, ['--foo=<int>'], ['--foo'])
    do_test(['--foo'], {'type': list}, [
      '--foo=<str> (--foo=<str>) ...',
      '--foo="[<str>, <str>, ...]"',
      '--foo="+[<str>, <str>, ...]"'
    ], ['--foo'])
    do_test(['--foo'], {'type': list, 'member_type': int},[
      '--foo=<int> (--foo=<int>) ...',
      '--foo="[<int>, <int>, ...]"',
      '--foo="+[<int>, <int>, ...]"'
    ], ['--foo'])
    do_test(['--foo'], {'type': list, 'member_type': dict},
            ['--foo="{\'key1\':val1,\'key2\':val2,...}" '
             '(--foo="{\'key1\':val1,\'key2\':val2,...}") ...',
             '--foo="[{\'key1\':val1,\'key2\':val2,...}, '
             '{\'key1\':val1,\'key2\':val2,...}, ...]"',
             '--foo="+[{\'key1\':val1,\'key2\':val2,...}, '
             '{\'key1\':val1,\'key2\':val2,...}, ...]"'],
            ['--foo'])
    do_test(['--foo'], {'type': dict}, ['--foo="{\'key1\':val1,\'key2\':val2,...}"'],
                                            ['--foo'])

    do_test(['--foo', '--bar'], {}, ['--foo=<str>', '--bar=<str>'], ['--foo', '--bar'])

  def test_non_global_scope(self):
    def do_test(args, kwargs, expected_display_args, expected_scoped_cmd_line_args,
                expected_unscoped_cmd_line_args):
      ohi = HelpInfoExtracter('bar.baz').get_option_help_info(args, kwargs)
      self.assertListEqual(expected_display_args, ohi.display_args)
      self.assertListEqual(expected_scoped_cmd_line_args, ohi.scoped_cmd_line_args)
      self.assertListEqual(expected_unscoped_cmd_line_args, ohi.unscoped_cmd_line_args)
    do_test(['-f'], {'type': bool}, ['--bar-baz-f'], ['--bar-baz-f'], ['-f'])
    do_test(['--foo'], {'type': bool}, ['--[no-]bar-baz-foo'],
            ['--bar-baz-foo', '--no-bar-baz-foo'], ['--foo', '--no-foo'])
    do_test(['--foo'], {'type': bool, 'implicit_value': False }, ['--[no-]bar-baz-foo'],
            ['--bar-baz-foo', '--no-bar-baz-foo'], ['--foo', '--no-foo'])

  def test_default(self):
    def do_test(args, kwargs, expected_default):
      # Defaults are computed in the parser and added into the kwargs, so we
      # must jump through this hoop in this test.
      parser = Parser(env={}, config=Config.load([]),
                      scope_info=GlobalOptionsRegistrar.get_scope_info(),
                      parent_parser=None, option_tracker=OptionTracker())
      parser.register(*args, **kwargs)
      oshi = HelpInfoExtracter.get_option_scope_help_info_from_parser(parser).basic
      self.assertEquals(1, len(oshi))
      ohi = oshi[0]
      self.assertEqual(expected_default, ohi.default)

    do_test(['--foo'], {'type': bool }, 'False')
    do_test(['--foo'], {'type': bool, 'default': True}, 'True')
    do_test(['--foo'], {'type': bool, 'implicit_value': False }, 'True')
    do_test(['--foo'], {'type': bool, 'implicit_value': False, 'default': False}, 'False')
    do_test(['--foo'], {}, 'None')
    do_test(['--foo'], {'type': int}, 'None')
    do_test(['--foo'], {'type': int, 'default': 42}, '42')
    do_test(['--foo'], {'type': list}, '[]')
    do_test(['--foo'], {'type': dict}, '{}')

  def test_deprecated(self):
    kwargs = {'removal_version': '999.99.9', 'removal_hint': 'do not use this'}
    ohi = HelpInfoExtracter('').get_option_help_info([], kwargs)
    self.assertEquals('999.99.9', ohi.removal_version)
    self.assertEquals('do not use this', ohi.removal_hint)
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
