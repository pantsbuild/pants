# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.option.custom_types import dict_option, list_option
from pants.option.errors import ParseError


class CustomTypesTest(unittest.TestCase):

  def _do_test(self, expected_val, s):
    if isinstance(expected_val, dict):
      val = dict_option(s)
    elif isinstance(expected_val, (list, tuple)):
      val = list_option(s)
    else:
      raise Exception('Expected value {0} is of unsupported type: {1}'.format(expected_val,
                                                                              type(expected_val)))
    self.assertEquals(expected_val, val)

  def _do_test_dict_error(self, s):
    with self.assertRaises(ParseError):
      self._do_test({}, s)

  def _do_test_list_error(self, s):
    with self.assertRaises(ParseError):
      self._do_test([], s)

  def test_dict(self):
    self._do_test({}, '{}')
    self._do_test({'a': 'b'}, '{ "a": "b" }')
    self._do_test({'a': 'b'}, "{ 'a': 'b' }")
    self._do_test({'a': [1, 2, 3]}, '{ "a": [1, 2, 3] }')
    self._do_test({'a': [1, 2, 3, 4]}, '{ "a": [1, 2] + [3, 4] }')
    self._do_test_dict_error({})
    self._do_test_dict_error({'a': 'b'})
    self._do_test_dict_error({'a': [1, 2, 3]})
    self._do_test_dict_error('[]')
    self._do_test_dict_error('[1, 2, 3]')
    self._do_test_dict_error('1')
    self._do_test_dict_error('"a"')

  def test_list(self):
    self._do_test([], '[]')
    self._do_test([1, 2, 3], '[1, 2, 3]')
    self._do_test((1, 2, 3), '1,2,3')
    self._do_test(['a', 'b', 'c'], '["a", "b", "c"]')
    self._do_test(['a', 'b', 'c'], "['a', 'b', 'c']")
    self._do_test([1, 2, 3, 4], '[1, 2] + [3, 4]')
    self._do_test((1, 2, 3, 4), '(1, 2) + (3, 4)')
    self._do_test_list_error([])
    self._do_test_list_error([1, 2, 3])
    self._do_test_list_error((1, 2, 3))
    self._do_test_list_error(['a', 'b', 'c'])
    self._do_test_list_error('{}')
    self._do_test_list_error('{"a": "b"}')
    self._do_test_list_error('1')
    self._do_test_list_error('"a"')
