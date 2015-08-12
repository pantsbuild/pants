# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_open

from pants.contrib.scrooge.tasks.thrift_util import find_includes, find_root_thrifts


class ThriftUtilTest(unittest.TestCase):
  def write(self, path, contents):
    with safe_open(path, 'w') as fp:
      fp.write(contents)
    return path

  def test_find_includes(self):
    with temporary_dir() as dir:
      a = os.path.join(dir, 'a')
      b = os.path.join(dir, 'b')

      main = self.write(os.path.join(a, 'main.thrift'), '''
        include "sub/a_included.thrift" //Todo commet
        include "b_included.thrift"
        include "c_included.thrift" #jibberish
        include "d_included.thrift" some ramdon
      ''')

      a_included = self.write(os.path.join(a, 'sub', 'a_included.thrift'), '# noop')
      b_included = self.write(os.path.join(b, 'b_included.thrift'), '# noop')
      c_included = self.write(os.path.join(b, 'c_included.thrift'), '# noop')

      self.assertEquals({a_included, b_included, c_included},
                        find_includes(basedirs={a, b}, source=main))

  def test_find_includes_exception(self):
    with temporary_dir() as dir:
      a = os.path.join(dir, 'a')

      main = self.write(os.path.join(a, 'main.thrift'), '''
        include "sub/a_included.thrift # Todo"
        include "b_included.thrift"
      ''')
      self.write(os.path.join(a, 'sub', 'a_included.thrift'), '# noop')
      self.assertRaises(ValueError, find_includes, basedirs={a}, source=main)

  def test_find_root_thrifts(self):
    with temporary_dir() as dir:
      root_1 = self.write(os.path.join(dir, 'root_1.thrift'), '# noop')
      root_2 = self.write(os.path.join(dir, 'root_2.thrift'), '# noop')
      self.assertEquals({root_1, root_2},
                        find_root_thrifts(basedirs=[], sources=[root_1, root_2]))

    with temporary_dir() as dir:
      root_1 = self.write(os.path.join(dir, 'root_1.thrift'), 'include "mid_1.thrift"')
      self.write(os.path.join(dir, 'mid_1.thrift'), 'include "leaf_1.thrift"')
      self.write(os.path.join(dir, 'leaf_1.thrift'), '# noop')
      root_2 = self.write(os.path.join(dir, 'root_2.thrift'), 'include "root_1.thrift"')
      self.assertEquals({root_2}, find_root_thrifts(basedirs=[], sources=[root_1, root_2]))
