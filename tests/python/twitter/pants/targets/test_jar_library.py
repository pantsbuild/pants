# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest

from pants.base.parse_context import ParseContext
from pants.base.target import Target, TargetDefinitionException
from pants.targets.jar_library import JarLibrary


class JarLibraryTest(unittest.TestCase):

  def test_validation(self):
    with ParseContext.temp('JarLibraryTest/test_validation'):
      target = Target(name='mybird')
      JarLibrary(name="test", dependencies=target)
      self.assertRaises(TargetDefinitionException, JarLibrary,
                        name="test1", dependencies=None)
