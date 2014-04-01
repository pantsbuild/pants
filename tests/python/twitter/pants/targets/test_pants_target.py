# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest

from pants.base.parse_context import ParseContext
from pants.base.target import TargetDefinitionException
from pants.targets.pants_target import Pants


class PantsTargetTest(unittest.TestCase):

  def test_validation(self):
    basedir = 'PantsTargetTest/test_validation'
    with ParseContext.temp(basedir):
      self.assertRaises(TargetDefinitionException, Pants, spec='fake')
      self.assertRaises(TargetDefinitionException, Pants, spec='%s:fake' % basedir)
