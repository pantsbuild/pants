# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest

from pants.base.parse_context import ParseContext
from pants.base.target import Target, TargetDefinitionException


class TargetTest(unittest.TestCase):

  def test_validation(self):
    with ParseContext.temp('TargetTest/test_validation'):
      self.assertRaises(TargetDefinitionException, Target, name=None)
      name = "test"
      self.assertEquals(Target(name=name).name, name)
