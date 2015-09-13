# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from pants.base.build_root import BuildRoot
from pants.util.contextutil import pushd, temporary_dir
from pants.util.dirutil import safe_mkdir, safe_mkdtemp, safe_rmtree, touch


class BuildRootTest(unittest.TestCase):

  def setUp(self):
    self.original_root = BuildRoot().path
    self.new_root = os.path.realpath(safe_mkdtemp())
    BuildRoot().reset()

  def tearDown(self):
    BuildRoot().reset()
    safe_rmtree(self.new_root)

  def test_via_set(self):
    BuildRoot().path = self.new_root
    self.assertEqual(self.new_root, BuildRoot().path)

  def test_reset(self):
    BuildRoot().path = self.new_root
    BuildRoot().reset()
    self.assertEqual(self.original_root, BuildRoot().path)

  def test_via_pantsini(self):
    with temporary_dir() as root:
      root = os.path.realpath(root)
      touch(os.path.join(root, 'pants.ini'))
      with pushd(root):
        self.assertEqual(root, BuildRoot().path)

      BuildRoot().reset()
      child = os.path.join(root, 'one', 'two')
      safe_mkdir(child)
      with pushd(child):
        self.assertEqual(root, BuildRoot().path)

  def test_temporary(self):
    with BuildRoot().temporary(self.new_root):
      self.assertEqual(self.new_root, BuildRoot().path)
    self.assertEqual(self.original_root, BuildRoot().path)

  def test_singleton(self):
    self.assertEqual(BuildRoot().path, BuildRoot().path)
    BuildRoot().path = self.new_root
    self.assertEqual(BuildRoot().path, BuildRoot().path)
