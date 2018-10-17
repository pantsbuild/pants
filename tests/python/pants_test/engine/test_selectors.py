# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import unittest
from builtins import object

from pants.engine.selectors import Select


class AClass(object):
  pass


class SelectorsTest(unittest.TestCase):
  def test_select_repr(self):
    self.assert_repr("Select(AClass)", Select(AClass))
    self.assert_repr("Select(AClass, optional=True)", Select(AClass, optional=True))

  def assert_repr(self, expected, selector):
    self.assertEqual(expected, repr(selector))
