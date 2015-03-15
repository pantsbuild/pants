# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from itertools import permutations

from pants.base.abbreviate_target_ids import abbreviate_target_ids


class AbbreviateTargetIdsTest(unittest.TestCase):
  def _test(self, expected, actual=None):
    if actual is None: actual = expected.keys()
    for p in permutations(actual):
      self.assertEqual(expected, abbreviate_target_ids(p))

  def test_empty(self):
    self._test({}, [])

  def test_single(self):
    self._test({'a': 'a'})
    self._test({'a.b.c': 'c'})

  def test_simple(self):
    self._test({'a': 'a', 'b': 'b', 'c': 'c'})
    self._test({'x.a': 'a', 'y.b': 'b', 'z.c': 'c'})

  def test_complex(self):
    self._test({'x.a': 'a', 'x.b': 'b', 'x.c': 'c'})
    self._test({'x.a': 'x.a', 'y.a': 'y.a', 'z.b': 'b'})
    self._test({'x.a': 'a', 'x.y.a': 'y.a', 'z.b': 'b'})
    self._test({'x.a': 'a', 'x.y.a': 'x.y.a', 'y.x.a': 'y.x.a'})

  def test_foo(self):
    self._test({'x.a': 'x.a', 'x.y.a': 'x.y.a', 'z.y.a': 'z.y.a', 'x.z.a': 'x.z.a'})
    self._test({'z.y.a': 'y.a', 'x.z.a': 'x.a'})

  def test_dups(self):
    d = {'x.a': 'a', 'x.b': 'b', 'x.c': 'c'}
    self._test(d, d.keys() + d.keys()[0:1])
