# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest

from pants.base.target import Target
from pants.base.exceptions import TargetDefinitionException
from pants.backend.jvm.targets.jar_library import JarLibrary


class JarLibraryTest(unittest.TestCase):
  pass
  # TODO(pl): This test is defunct, but we should be testing the behavior
  # of JarLibrary
  # def test_validation(self):
  #   with ParseContext.temp('JarLibraryTest/test_validation'):
  #     target = Target(name='mybird')
  #     JarLibrary(name="test", dependencies=target)
  #     self.assertRaises(TargetDefinitionException, JarLibrary,
  #                       name="test1", dependencies=None)
