# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from textwrap import dedent

from pants.option.custom_types import ListValueComponent, UnsetBool, dict_option, list_option
from pants.option.errors import ParseError
from pants.util.strutil import ensure_binary


class CustomTypesTest(unittest.TestCase):

  def _do_test(self, expected_val, s):
    if isinstance(expected_val, dict):
      val = dict_option(s).val
    elif isinstance(expected_val, (list, tuple)):
      val = list_option(s).val
    else:
      raise Exception('Expected value {0} is of unsupported type: {1}'.format(expected_val,
                                                                              type(expected_val)))
    self.assertEquals(expected_val, val)

  def _do_test_dict_error(self, s):
    with self.assertRaises(ParseError):
      self._do_test({}, s)

  def _do_split(self, expr, expected):
    self.assertEqual(expected, ListValueComponent._split_modifier_expr(expr))

  def test_unset_bool(self):
    # UnsetBool should only be use-able as a singleton value via its type.
    with self.assertRaises(NotImplementedError):
      UnsetBool()

  def test_dict(self):
    self._do_test({}, '{}')
    self._do_test({'a': 'b'}, '{ "a": "b" }')
    self._do_test({'a': 'b'}, "{ 'a': 'b' }")
    self._do_test({'a': [1, 2, 3]}, '{ "a": [1, 2, 3] }')
    self._do_test({'a': [1, 2, 3, 4]}, '{ "a": [1, 2] + [3, 4] }')
    self._do_test_dict_error('[]')
    self._do_test_dict_error('[1, 2, 3]')
    self._do_test_dict_error('1')
    self._do_test_dict_error('"a"')

  def test_list(self):
    self._do_test([], '[]')
    self._do_test([1, 2, 3], '[1, 2, 3]')
    self._do_test([1, 2, 3], '(1, 2, 3)')
    self._do_test(['a', 'b', 'c'], '["a", "b", "c"]')
    self._do_test(['a', 'b', 'c'], "['a', 'b', 'c']")
    self._do_test([1, 2, 3, 4], '[1, 2] + [3, 4]')
    self._do_test([1, 2, 3, 4], '(1, 2) + (3, 4)')
    self._do_test(['a"'], 'a"')
    self._do_test(["a'"], "a'")
    self._do_test(["\"a'"], "\"a'")
    self._do_test(["'a\""], "'a\"")
    self._do_test(['a"""a'], 'a"""a')
    self._do_test(['1,2'], '1,2')
    self._do_test([1, 2], '+[1,2]')
    self._do_test(['\\'], '\\')

  def test_split_list_modifier_expressions(self):
    self._do_split('1', ['1'])
    self._do_split('foo', ['foo'])
    self._do_split('1,2', ['1,2'])
    self._do_split('[1,2]', ['[1,2]'])
    self._do_split('[1,2],[3,4]', ['[1,2],[3,4]'])
    self._do_split('+[1,2],[3,4]', ['+[1,2],[3,4]'])
    self._do_split('[1,2],-[3,4]', ['[1,2],-[3,4]'])
    self._do_split('+[1,2],foo', ['+[1,2],foo'])

    self._do_split('+[1,2],-[3,4]', ['+[1,2]', '-[3,4]'])
    self._do_split('-[1,2],+[3,4]', ['-[1,2]', '+[3,4]'])
    self._do_split('-[1,2],+[3,4],-[5,6],+[7,8]', ['-[1,2]', '+[3,4]', '-[5,6]', '+[7,8]'])
    self._do_split('+[-1,-2],-[-3,-4]', ['+[-1,-2]', '-[-3,-4]'])
    self._do_split('+["-"],-["+"]', ['+["-"]', '-["+"]'])
    self._do_split('+["+[3,4]"],-["-[4,5]"]', ['+["+[3,4]"]', '-["-[4,5]"]'])

    # Spot-check that this works with literal tuples as well as lists.
    self._do_split('+(1,2),-(3,4)', ['+(1,2)', '-(3,4)'])
    self._do_split('-[1,2],+[3,4],-(5,6),+[7,8]', ['-[1,2]', '+[3,4]', '-(5,6)', '+[7,8]'])
    self._do_split('+(-1,-2),-[-3,-4]', ['+(-1,-2)', '-[-3,-4]'])
    self._do_split('+("+(3,4)"),-("-(4,5)")', ['+("+(3,4)")', '-("-(4,5)")'])

    # Check that whitespace around the comma is OK.
    self._do_split('+[1,2] , -[3,4]', ['+[1,2]', '-[3,4]'])
    self._do_split('+[1,2]    ,-[3,4]', ['+[1,2]', '-[3,4]'])
    self._do_split('+[1,2] ,     -[3,4]', ['+[1,2]', '-[3,4]'])

    # We will split some invalid expressions, but that's OK, we'll error out later on the
    # broken components.
    self._do_split('+1,2],-[3,4', ['+1,2]','-[3,4'])
    self._do_split('+(1,2],-[3,4)', ['+(1,2]', '-[3,4)'])

  # The heuristic list modifier expression splitter cannot handle certain very unlikely cases.
  @unittest.expectedFailure
  def test_split_unlikely_list_modifier_expression(self):
    # Example of the kind of (unlikely) values that will defeat our heuristic, regex-based
    # splitter of list modifier expressions.
    funky_string = '],+['
    self._do_split('+["{}"],-["foo"]'.format(funky_string),
                   ['+["{}"]'.format(funky_string), '-["foo"]'])

  def test_unicode_comments(self):
    """We had a bug where unicode characters in comments would cause the option parser to fail.

    Without the fix to the option parser, this test case reproduces the error:

    UnicodeDecodeError: 'ascii' codec can't decode byte 0xe2 in position 44:
                       ordinal not in range(128)
    """
    self._do_test(
      ['Hi there!', 'This is an element in a list of strings.'],
      ensure_binary(dedent(u"""
      [
        'Hi there!',
        # This is a comment with ‘sneaky‘ unicode characters.
        'This is an element in a list of strings.',
        # This is a comment with an obvious unicode character ☺.
        ]
      """).strip()),
    )
