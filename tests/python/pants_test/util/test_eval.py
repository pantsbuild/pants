# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

import six

from pants.util.eval import parse_literal


class ParseLiteralTest(unittest.TestCase):

  def test_success_simple(self):
    literal = parse_literal("'42'", acceptable_types=six.string_types)
    self.assertEqual('42', literal)

  def test_success_mixed(self):
    literal = parse_literal('42', acceptable_types=(float, int))
    self.assertEqual(42, literal)

  def test_failure_syntax(self):
    with self.assertRaises(ValueError):
      # Only literals are allowed!
      parse_literal('1+2', acceptable_types=int)

  def test_failure_type(self):
    # Prove there is no syntax error in the raw value.
    literal = parse_literal('1.0', acceptable_types=float)
    self.assertEqual(1.0, literal)

    # Now we can safely assume the ValueError is raise due to type checking.
    with self.assertRaises(ValueError):
      parse_literal('1.0', acceptable_types=int)

  def test_custom_error_type(self):
    class CustomError(Exception):
      pass

    with self.assertRaises(CustomError):
      parse_literal('1.0', acceptable_types=int, raise_type=CustomError)
