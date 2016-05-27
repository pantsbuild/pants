# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.util.objects import datatype


class DatatypeTest(unittest.TestCase):
  def test_wut(self):
    data_type = datatype('Foo', ['val'])
    intcarrying = data_type(1)
    strcarrying = data_type('string')

    self.assertNotEqual(strcarrying, intcarrying)
    self.assertFalse(strcarrying == intcarrying)
