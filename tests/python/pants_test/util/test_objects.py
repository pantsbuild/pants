# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import copy
import unittest

from pants.util.objects import datatype


class AbsClass(object):
  pass


class ReturnsNotImplemented(object):
  def __eq__(self, other):
    return NotImplemented


class DatatypeTest(unittest.TestCase):

  def test_eq_with_not_implemented_super(self):
    class DatatypeSuperNotImpl(datatype('Foo', ['val']), ReturnsNotImplemented, tuple):
      pass

    self.assertNotEqual(DatatypeSuperNotImpl(1), DatatypeSuperNotImpl(1))

  def test_repr(self):
    bar = datatype('Bar', ['val', 'zal'])
    self.assertEqual('Bar(val=1, zal=1)', repr(bar(1, 1)))

    class Foo(datatype('F', ['val']), AbsClass):
      pass

    # Maybe this should be 'Foo(val=1)'?
    self.assertEqual('F(val=1)', repr(Foo(1)))

  def test_not_iterable_by_default(self):
    bar = datatype('Bar', ['val'])
    with self.assertRaises(TypeError):
      for x in bar(1):
        pass

  def test_iterable_when_is_iterable(self):
    bar = datatype('Bar', ['val'], is_iterable=True)
    self.assertEqual([1], [x for x in bar(1)])

  def test_deep_copy_non_iterable(self):
    # deep copy calls into __getnewargs__, which namedtuple defines as implicitly using __iter__.

    bar = datatype('Bar', ['val'])

    self.assertEqual(bar(1), copy.deepcopy(bar(1)))

  def test_deep_copy_iterable(self):
    bar = datatype('Bar', ['val'], is_iterable=True)

    self.assertEqual(bar(1), copy.deepcopy(bar(1)))

  def test_as_dict_non_iterable(self):
    bar = datatype('Bar', ['val'])

    self.assertEqual({'val': 1}, bar(1)._asdict())

  def test_replace_non_iterable(self):
    bar = datatype('Bar', ['val', 'zal'])

    self.assertEqual(bar(1, 3), bar(1, 2)._replace(zal=3))
