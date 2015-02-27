# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

import pytest
import unittest

from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import touch, chmod_plus_x
from pants.contrib.cpp.toolchain.cpp_toolchain import CppToolchain


class TestCppToolchainTest(unittest.TestCase):
  def setUp(self):
    super(TestCppToolchainTest, self).setUp()

  def test_default_compiler_from_environ(self):
    with environment_as(CXX='g++'):
      assert(CppToolchain().compiler == CppToolchain().register_tool('g++'))

  def test_invalid_compiler(self):
    with pytest.raises(CppToolchain.Error):
      CppToolchain('not-a-command')

  def test_tool_registration(self):
    with temporary_dir() as tool_root:
      newpath = os.pathsep.join((os.environ['PATH'], tool_root))
      with environment_as(PATH=newpath):
        GOODTOOL = 'good-tool'
        goodtool_path = os.path.join(tool_root, GOODTOOL)
        touch(goodtool_path)
        chmod_plus_x(goodtool_path)
        CppToolchain().register_tool(GOODTOOL)

  def test_invalid_tool_registration(self):
    with pytest.raises(CppToolchain.Error):
      CppToolchain().register_tool('not-a-command')
