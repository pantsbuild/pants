# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

import six

from pants.util.eval import parse_expression


class ParseLiteralTest(unittest.TestCase):

  def test_success_simple(self):
    literal = parse_expression("'42'", acceptable_types=six.string_types)
    self.assertEqual('42', literal)

  def test_success_mixed(self):
    literal = parse_expression('42', acceptable_types=(float, int))
    self.assertEqual(42, literal)

  def test_success_complex_syntax(self):
    self.assertEqual(3, parse_expression('1+2', acceptable_types=int))

  def test_success_list_concat(self):
    # This is actually useful in config files.
    self.assertEqual([1, 2, 3], parse_expression('[1, 2] + [3]', acceptable_types=list))

  def test_failure_type(self):
    # Prove there is no syntax error in the raw value.
    literal = parse_expression('1.0', acceptable_types=float)
    self.assertEqual(1.0, literal)

    # Now we can safely assume the ValueError is raise due to type checking.
    with self.assertRaises(ValueError):
      parse_expression('1.0', acceptable_types=int)

  def test_custom_error_type(self):
    class CustomError(Exception):
      pass

    with self.assertRaises(CustomError):
      parse_expression('1.0', acceptable_types=int, raise_type=CustomError)
