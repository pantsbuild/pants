# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Illustrate using Thrift-generated code from Python.

import unittest

from com.pants.examples.distance.ttypes import Distance
from com.pants.examples.precipitation.ttypes import Precipitation


class UseThriftTest(unittest.TestCase):
  def test_make_it_rain(self):
    distance = Distance()
    self.assertTrue(hasattr(distance, 'Number'))
    sprinkle = Precipitation()
    self.assertTrue(hasattr(sprinkle, 'distance'))
