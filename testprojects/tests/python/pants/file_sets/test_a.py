# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest


class DummyTest(unittest.TestCase):
  def test_foo(self):
    a = 10
    b = 20
    self.assertEqual(a*2, b)
