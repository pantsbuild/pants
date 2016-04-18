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
from pathspec.gitignore import GitIgnorePattern

from pants.util.dirutil import safe_mkdir, touch


class ProjectTreeTestBase(unittest.TestCase):
  """
    :API: public
  """

  def fullpath(self, path):
    """
    :API: public
    """
    return os.path.join(self.root_dir, path)

  def makedirs(self, path):
    """
    :API: public
    """
    safe_mkdir(self.fullpath(path))

  def touch(self, path):
    """
    :API: public
    """
    touch(self.fullpath(path))

  def _create_ignore_spec(self, ignore_patterns):
    """
    :API: public
    """
    return PathSpec.from_lines(GitIgnorePattern, ignore_patterns or [])

  def setUp(self):
    """
    :API: public
    """
    self.base_dir = tempfile.mkdtemp()
    self._project_tree = None

    # Seed a BUILD outside the build root that should not be detected
    touch(os.path.join(self.base_dir, 'BUILD'))

    self.root_dir = os.path.join(self.base_dir, 'root')

    # make 'root/'
    self.makedirs('')

    # make 'root/...'
    self.touch('apple')
    self.touch('orange')
    self.touch('banana')

    # make 'root/fruit/'
    self.makedirs('fruit')

    # make 'root/fruit/...'
    self.touch('fruit/apple')
    self.touch('fruit/orange')
    self.touch('fruit/banana')

    # make 'root/fruit/fruit/'
    self.makedirs('fruit/fruit')

    # make 'root/fruit/fruit/...'
    self.touch('fruit/fruit/apple')
    self.touch('fruit/fruit/orange')
    self.touch('fruit/fruit/banana')

    self.makedirs('grocery')
    self.touch('grocery/fruit')

    self.cwd = os.getcwd()
    os.chdir(self.root_dir)

  def tearDown(self):
    """
    :API: public
    """
    shutil.rmtree(self.base_dir)
    os.chdir(self.cwd)
