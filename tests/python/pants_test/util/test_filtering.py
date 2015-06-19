# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.util.filtering import create_filter, create_filters, wrap_filters


class FilteringTest(unittest.TestCase):
  def _divides_by(self, divisor_str):
    return lambda n: n % int(divisor_str) == 0

  def test_create_filter(self):
    divides_by_2 = create_filter('2', self._divides_by)
    self.assertTrue(divides_by_2(2))
    self.assertFalse(divides_by_2(3))
    self.assertTrue(divides_by_2(4))
    self.assertTrue(divides_by_2(6))

  def test_create_filters(self):
    # This tests that create_filters() properly captures different closures.
    divides_by_2, divides_by_3 = create_filters(['2', '3'], self._divides_by)
    self.assertTrue(divides_by_2(2))
    self.assertFalse(divides_by_2(3))
    self.assertTrue(divides_by_2(4))
    self.assertTrue(divides_by_2(6))

    self.assertFalse(divides_by_3(2))
    self.assertTrue(divides_by_3(3))
    self.assertFalse(divides_by_3(4))
    self.assertTrue(divides_by_3(6))

  def test_wrap_filters(self):
    divides_by_6 = wrap_filters(create_filters(['2', '3'], self._divides_by))
    self.assertFalse(divides_by_6(2))
    self.assertFalse(divides_by_6(3))
    self.assertTrue(divides_by_6(6))
    self.assertFalse(divides_by_6(9))
    self.assertTrue(divides_by_6(12))

  def test_list_filter(self):
    divides_by_2_or_3 = create_filter('2,3', self._divides_by)
    self.assertTrue(divides_by_2_or_3(2))
    self.assertTrue(divides_by_2_or_3(3))
    self.assertTrue(divides_by_2_or_3(4))
    self.assertFalse(divides_by_2_or_3(5))
    self.assertTrue(divides_by_2_or_3(6))

  def test_explicit_plus_filter(self):
    divides_by_2_or_3 = create_filter('+2,3', self._divides_by)
    self.assertTrue(divides_by_2_or_3(2))
    self.assertTrue(divides_by_2_or_3(3))
    self.assertTrue(divides_by_2_or_3(4))
    self.assertFalse(divides_by_2_or_3(5))
    self.assertTrue(divides_by_2_or_3(6))

  def test_negated_filter(self):
    # This tests that the negation applies to the entire list.
    coprime_to_2_and_3 = create_filter('-2,3', self._divides_by)
    self.assertFalse(coprime_to_2_and_3(2))
    self.assertFalse(coprime_to_2_and_3(3))
    self.assertFalse(coprime_to_2_and_3(4))
    self.assertTrue(coprime_to_2_and_3(5))
    self.assertFalse(coprime_to_2_and_3(6))
