# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
import tempfile
import unittest
from abc import abstractmethod

from pants.base.build_file import BuildFile
from pants.util.dirutil import safe_mkdir, touch


class BuildFileTestBase(unittest.TestCase):
  def fullpath(self, path):
    return os.path.join(self.root_dir, path)

  def makedirs(self, path):
    safe_mkdir(self.fullpath(path))

  def touch(self, path):
    touch(self.fullpath(path))

  def scan_buildfiles(self, root_dir, base_path=None, spec_excludes=None):
    return BuildFile.scan_project_tree_buildfiles(self._project_tree, root_dir, base_path, spec_excludes)

  @abstractmethod
  def create_project_tree(self, build_root):
    pass

  def create_buildfile(self, path, must_exist=True):
    return BuildFile(self._project_tree, self.root_dir, path, must_exist=must_exist)

  def setUp(self):
    self.base_dir = tempfile.mkdtemp()

    # Seed a BUILD outside the build root that should not be detected
    touch(os.path.join(self.base_dir, 'BUILD'))

    self.root_dir = os.path.join(self.base_dir, 'root')

    self.touch('grandparent/parent/BUILD')
    self.touch('grandparent/parent/BUILD.twitter')
    # Tricky!  This is a directory
    self.makedirs('grandparent/parent/BUILD.dir')
    self.makedirs('grandparent/BUILD')
    self.touch('BUILD')
    self.touch('BUILD.twitter')
    self.touch('grandparent/parent/child1/BUILD')
    self.touch('grandparent/parent/child1/BUILD.twitter')
    self.touch('grandparent/parent/child2/child3/BUILD')
    self.makedirs('grandparent/parent/child2/BUILD')
    self.makedirs('grandparent/parent/child4')
    self.touch('grandparent/parent/child5/BUILD')
    self.makedirs('path-that-does-exist')
    self.touch('path-that-does-exist/BUILD.invalid.suffix')

    # This exercises https://github.com/pantsbuild/pants/issues/1742
    # Prior to that fix, BUILD directories were handled, but not if there was a valid BUILD file
    # sibling.
    self.makedirs('issue_1742/BUILD')
    self.touch('issue_1742/BUILD.sibling')

    self._project_tree = self.create_project_tree(self.root_dir)

  def tearDown(self):
    shutil.rmtree(self.base_dir)
