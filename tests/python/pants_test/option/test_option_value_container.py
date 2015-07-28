# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import copy
import unittest

from pants.option.option_value_container import OptionValueContainer
from pants.option.ranked_value import RankedValue


class OptionValueContainerTest(unittest.TestCase):
  def test_standard_values(self):
    o = OptionValueContainer()
    o.foo = 1
    self.assertEqual(1, o.foo)

    with self.assertRaises(AttributeError):
      o.bar

  def test_forwarding(self):
    o = OptionValueContainer()
    o.add_forwardings({'foo': 'bar'})
    o.bar = 1
    self.assertEqual(1, o.foo)
    o.bar = 2
    self.assertEqual(2, o.foo)

    o.add_forwardings({'baz': 'qux'})
    o.qux = 3
    self.assertEqual(2, o.foo)
    self.assertEqual(3, o.baz)

    # Direct setting overrides forwarding.
    o.foo = 4
    self.assertEqual(4, o.foo)

  def test_value_ranking(self):
    o = OptionValueContainer()
    o.add_forwardings({'foo': 'bar'})
    o.bar = RankedValue(RankedValue.CONFIG, 11)
    self.assertEqual(11, o.foo)
    self.assertEqual(RankedValue.CONFIG, o.get_rank('foo'))
    o.bar = RankedValue(RankedValue.HARDCODED, 22)
    self.assertEqual(11, o.foo)
    self.assertEqual(RankedValue.CONFIG, o.get_rank('foo'))
    o.bar = RankedValue(RankedValue.ENVIRONMENT, 33)
    self.assertEqual(33, o.foo)
    self.assertEqual(RankedValue.ENVIRONMENT, o.get_rank('foo'))
    o.bar = 44  # No explicit rank is assumed to be a FLAG.
    self.assertEqual(44, o.foo)
    self.assertEqual(RankedValue.FLAG, o.get_rank('foo'))

  def test_indexing(self):
    o = OptionValueContainer()
    o.add_forwardings({'foo': 'bar'})
    o.bar = 1
    self.assertEqual(1, o['foo'])
    self.assertEqual(1, o['bar'])

    self.assertEqual(1, o.get('foo'))
    self.assertEqual(1, o.get('foo', 2))
    self.assertIsNone(o.get('unknown'))
    self.assertEqual(2, o.get('unknown', 2))

    with self.assertRaises(AttributeError):
      o['baz']

  def test_iterator(self):
    o = OptionValueContainer()
    o.add_forwardings({'a': '_a'})
    o.add_forwardings({'b': '_b'})
    o.add_forwardings({'b_prime': '_b'})  # Should be elided in favor of b.
    o.add_forwardings({'c': '_c'})
    names = list(iter(o))
    self.assertListEqual(['a', 'b', 'c'], names)

  def test_copy(self):
    # copy semantics can get hairy when overriding __setattr__/__getattr__, so we test them.
    o = OptionValueContainer()
    o.add_forwardings({'foo': 'bar'})
    o.add_forwardings({'baz': 'qux'})
    o.bar = 1
    o.qux = { 'a': 111 }
    p = copy.copy(o)
    o.baz['b'] = 222  # Add to original dict.
    self.assertEqual(1, p.foo)
    self.assertEqual({ 'a': 111, 'b': 222 }, p.baz)  # Ensure dict was not copied.

  def test_deepcopy(self):
    # deepcopy semantics can get hairy when overriding __setattr__/__getattr__, so we test them.
    o = OptionValueContainer()
    o.add_forwardings({'foo': 'bar'})
    o.add_forwardings({'baz': 'qux'})
    o.bar = 1
    o.qux = {'a': 111}
    p = copy.deepcopy(o)
    o.baz['b'] = 222  # Add to original dict.
    self.assertEqual(1, p.foo)
    self.assertEqual({'a': 111}, p.baz)  # Ensure dict was copied.
