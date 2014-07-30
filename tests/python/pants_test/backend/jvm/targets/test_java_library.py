# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest

from pants.backend.jvm.targets.java_library import JavaLibrary


class JavaLibraryTest(unittest.TestCase):

  def testJavaLibraryBuildFileAlias(self):
    # Having a hard-coded 'java_library' constant here to remind
    # source code modifier that changing a target build file alias
    # shouldn't be done automagically and lightly.
    self.assertEquals('java_library', JavaLibrary.get_build_file_alias())
