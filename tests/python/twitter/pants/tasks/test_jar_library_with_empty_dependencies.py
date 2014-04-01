# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest

import pytest

from pants.base.parse_context import ParseContext
from pants.base.target import TargetDefinitionException
from pants.targets.jar_library import JarLibrary


class JarLibraryWithEmptyDependenciesTest(unittest.TestCase):

  def test_empty_dependencies(self):
    with ParseContext.temp():
      JarLibrary("test-jar-library-with-empty-dependencies", [])

  def test_no_dependencies(self):
    with pytest.raises(TargetDefinitionException):
      with ParseContext.temp():
        JarLibrary("test-jar-library-with-empty-dependencies", None)
