# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from contextlib import contextmanager

from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import chmod_plus_x, touch

from pants.contrib.cpp.toolchain.cpp_toolchain import CppToolchain


class CppToolchainTest(unittest.TestCase):
  @contextmanager
  def tool(self, name):
    with temporary_dir() as tool_root:
      tool_path = os.path.join(tool_root, name)
      touch(tool_path)
      chmod_plus_x(tool_path)
      new_path = os.pathsep.join([tool_root] + os.environ.get('PATH', '').split(os.pathsep))
      with environment_as(PATH=new_path):
        yield tool_path

  def test_default_compiler_from_environ(self):
    with self.tool('g++') as tool_path:
      with environment_as(CXX='g++'):
        self.assertEqual(CppToolchain().compiler, tool_path)
        self.assertEqual(CppToolchain().compiler,
                         CppToolchain().register_tool(name='compiler', tool=tool_path))

  def test_invalid_compiler(self):
    cpp_toolchain = CppToolchain(compiler='not-a-command')
    with self.assertRaises(CppToolchain.Error):
      cpp_toolchain.compiler

  def test_tool_registration(self):
    with self.tool('good-tool') as tool_path:
      self.assertEqual(tool_path, CppToolchain().register_tool(name='foo', tool='good-tool'))

  def test_invalid_tool_registration(self):
    with self.assertRaises(CppToolchain.Error):
      CppToolchain().register_tool('not-a-command')
