# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from org.pantsbuild.example.distance.ttypes import Distance
from org.pantsbuild.example.precipitation.ttypes import Precipitation


# Illustrate using Thrift-generated code from Python.
class UseThriftTest(unittest.TestCase):
  def test_make_it_rain(self):
    distance = Distance()
    self.assertTrue(hasattr(distance, 'Number'))
    sprinkle = Precipitation()
    self.assertTrue(hasattr(sprinkle, 'distance'))
