# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest
from textwrap import dedent
from typing import Dict, List, Union

from pants.option.custom_types import ListValueComponent, UnsetBool, dict_option, list_option
from pants.option.errors import ParseError


class CustomTypesTest(unittest.TestCase):

  ValidPrimitives = Union[int, str]
  ParsedList = List[ValidPrimitives]
  ParsedDict = Dict[str, Union[ValidPrimitives, ParsedList]]

  def assert_parsed(self, s: str, *, expected: Union[ParsedList, ParsedDict]) -> None:
    custom_type = dict_option(s) if isinstance(expected, dict) else list_option(s)
    self.assertEqual(expected, custom_type.val)

  def assert_split_list(self, expr: str, *, expected: List[str]) -> None:
    self.assertEqual(expected, ListValueComponent._split_modifier_expr(expr))

  def test_unset_bool(self):
    # UnsetBool should only be use-able as a singleton value via its type.
    with self.assertRaises(NotImplementedError):
      UnsetBool()

  def test_dict(self) -> None:
    def assert_dict_error(s: str) -> None:
      with self.assertRaises(ParseError):
        self.assert_parsed(s, expected={})

    self.assert_parsed('{}', expected={})
    self.assert_parsed('{ "a": "b" }', expected={'a': 'b'})
    self.assert_parsed("{ 'a': 'b' }", expected={'a': 'b'})
    self.assert_parsed('{ "a": [1, 2, 3] }', expected={'a': [1, 2, 3]})
    self.assert_parsed('{ "a": [1, 2] + [3, 4] }', expected={'a': [1, 2, 3, 4]})
    assert_dict_error('[]')
    assert_dict_error('[1, 2, 3]')
    assert_dict_error('1')
    assert_dict_error('"a"')

  def test_list(self) -> None:
    self.assert_parsed('[]', expected=[])
    self.assert_parsed('[1, 2, 3]', expected=[1, 2, 3])
    self.assert_parsed('(1, 2, 3)', expected=[1, 2, 3])
    self.assert_parsed('["a", "b", "c"]', expected=['a', 'b', 'c'])
    self.assert_parsed("['a', 'b', 'c']", expected=['a', 'b', 'c'])
    self.assert_parsed('[1, 2] + [3, 4]', expected=[1, 2, 3, 4])
    self.assert_parsed('(1, 2) + (3, 4)', expected=[1, 2, 3, 4])
    self.assert_parsed('a"', expected=['a"'])
    self.assert_parsed("a'", expected=["a'"])
    self.assert_parsed("\"a'", expected=["\"a'"])
    self.assert_parsed("'a\"", expected=["'a\""])
    self.assert_parsed('a"""a', expected=['a"""a'])
    self.assert_parsed('1,2', expected=['1,2'])
    self.assert_parsed('+[1,2]', expected=[1, 2])
    self.assert_parsed('\\', expected=['\\'])

  def test_split_list_modifier_expressions(self) -> None:
    self.assert_split_list('1', expected=['1'])
    self.assert_split_list('foo', expected=['foo'])
    self.assert_split_list('1,2', expected=['1,2'])
    self.assert_split_list('[1,2]', expected=['[1,2]'])
    self.assert_split_list('[1,2],[3,4]', expected=['[1,2],[3,4]'])
    self.assert_split_list('+[1,2],[3,4]', expected=['+[1,2],[3,4]'])
    self.assert_split_list('[1,2],-[3,4]', expected=['[1,2],-[3,4]'])
    self.assert_split_list('+[1,2],foo', expected=['+[1,2],foo'])

    self.assert_split_list('+[1,2],-[3,4]', expected=['+[1,2]', '-[3,4]'])
    self.assert_split_list('-[1,2],+[3,4]', expected=['-[1,2]', '+[3,4]'])
    self.assert_split_list(
      '-[1,2],+[3,4],-[5,6],+[7,8]', expected=['-[1,2]', '+[3,4]', '-[5,6]', '+[7,8]']
    )
    self.assert_split_list('+[-1,-2],-[-3,-4]', expected=['+[-1,-2]', '-[-3,-4]'])
    self.assert_split_list('+["-"],-["+"]', expected=['+["-"]', '-["+"]'])
    self.assert_split_list('+["+[3,4]"],-["-[4,5]"]', expected=['+["+[3,4]"]', '-["-[4,5]"]'])

    # Spot-check that this works with literal tuples as well as lists.
    self.assert_split_list('+(1,2),-(3,4)', expected=['+(1,2)', '-(3,4)'])
    self.assert_split_list(
      '-[1,2],+[3,4],-(5,6),+[7,8]', expected=['-[1,2]', '+[3,4]', '-(5,6)', '+[7,8]']
    )
    self.assert_split_list('+(-1,-2),-[-3,-4]', expected=['+(-1,-2)', '-[-3,-4]'])
    self.assert_split_list('+("+(3,4)"),-("-(4,5)")', expected=['+("+(3,4)")', '-("-(4,5)")'])

    # Check that whitespace around the comma is OK.
    self.assert_split_list('+[1,2] , -[3,4]', expected=['+[1,2]', '-[3,4]'])
    self.assert_split_list('+[1,2]    ,-[3,4]', expected=['+[1,2]', '-[3,4]'])
    self.assert_split_list('+[1,2] ,     -[3,4]', expected=['+[1,2]', '-[3,4]'])

    # We will split some invalid expressions, but that's OK, we'll error out later on the
    # broken components.
    self.assert_split_list('+1,2],-[3,4', expected=['+1,2]', '-[3,4'])
    self.assert_split_list('+(1,2],-[3,4)', expected=['+(1,2]', '-[3,4)'])

  # The heuristic list modifier expression splitter cannot handle certain very unlikely cases.
  @unittest.expectedFailure
  def test_split_unlikely_list_modifier_expression(self) -> None:
    # Example of the kind of (unlikely) values that will defeat our heuristic, regex-based
    # splitter of list modifier expressions.
    funky_string = '],+['
    self.assert_split_list(
      f'+["{funky_string}"],-["foo"]', expected=[f'+["{funky_string}"]', '-["foo"]']
    )

  def test_unicode_comments(self) -> None:
    """We had a bug where unicode characters in comments would cause the option parser to fail.

    Without the fix to the option parser, this test case reproduces the error:

    UnicodeDecodeError: 'ascii' codec can't decode byte 0xe2 in position 44:
                       ordinal not in range(128)
    """
    self.assert_parsed(
      dedent("""
         [
           'Hi there!',
           # This is a comment with ‘sneaky‘ unicode characters.
           'This is an element in a list of strings.',
           # This is a comment with an obvious unicode character ☺.
           ]
         """).strip(),
      expected=['Hi there!', 'This is an element in a list of strings.'],
    )
