# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.birds.duck.ttypes import Duck
from pants.birds.goose.ttypes import Goose


class ThritNamespacePackagesTest(unittest.TestCase):
  def test_thrift_namespaces(self):
    """The 'test' here is the very fact that we can successfully import the generated thrift code
    with a shared package prefix (twitter.birds) from two different eggs.
    However there's no harm in also exercising the thrift objects, just to be sure we can."""
    myDuck = Duck()
    myDuck.quack = 'QUACKQUACKQUACK'
    myGoose = Goose()
    myGoose.laysGoldenEggs = True
