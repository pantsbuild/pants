# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
import tempfile
import unittest

from pathspec import PathSpec
from pathspec.patterns.gitwildmatch import GitWildMatchPattern

from pants.base.build_file import BuildFile
from pants.util.dirutil import safe_mkdir, touch


class BuildFileTestBase(unittest.TestCase):
  def fullpath(self, path):
    return os.path.join(self.root_dir, path)

  def makedirs(self, path):
    safe_mkdir(self.fullpath(path))

  def touch(self, path):
    touch(self.fullpath(path))

  def _create_ignore_spec(self, build_ignore_patterns):
    return PathSpec.from_lines(GitWildMatchPattern, build_ignore_patterns or [])

  def scan_buildfiles(self, base_relpath, build_ignore_patterns=None):
    return BuildFile.scan_build_files(self._project_tree, base_relpath,
                                      build_ignore_patterns=self._create_ignore_spec(build_ignore_patterns))

  def create_buildfile(self, relpath):
    return BuildFile(self._project_tree, relpath)

  def get_build_files_family(self, relpath, build_ignore_patterns=None):
    return BuildFile.get_build_files_family(self._project_tree, relpath,
                                            build_ignore_patterns=self._create_ignore_spec(build_ignore_patterns))

  def setUp(self):
    self.base_dir = tempfile.mkdtemp()
    self._project_tree = None

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

  def tearDown(self):
    shutil.rmtree(self.base_dir)
