# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.exceptions import TargetDefinitionException
from pants_test.base_test import BaseTest


class JarLibraryTest(BaseTest):

  def test_missing_jars(self):
    def missing_jars():
      JarLibrary(name='jl', jars=[]) 
    self.assertRaises(TargetDefinitionException, missing_jars)
