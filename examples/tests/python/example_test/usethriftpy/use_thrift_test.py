# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Illustrate using Thrift-generated code from Python.

import unittest2 as unittest

from com.pants.examples.distance.ttypes import Distance
from com.pants.examples.precipitation.ttypes import Precipitation
from com.pants.examples.keywords.keywords.ttypes import Keywords
from com.pants.examples.keywords.another.ttypes import Another
from thrift.protocol import TProtocol

class UseThriftTest(unittest.TestCase):
  def test_make_it_rain(self):
    distance = Distance()
    self.assertTrue(hasattr(distance, 'Number'))
    sprinkle = Precipitation()
    self.assertTrue(hasattr(sprinkle, 'distance'))
    sprinkle = Keywords()
    self.assertTrue(hasattr(sprinkle, 'from_'))
    self.assertTrue(hasattr(sprinkle, 'None_'))

    another = Another()
    self.assertTrue(hasattr(another, 'from_'))
    self.assertTrue(hasattr(another, 'None_'))
