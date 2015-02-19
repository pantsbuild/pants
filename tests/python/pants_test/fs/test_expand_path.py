# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from contextlib import contextmanager

from pants.fs.fs import expand_path
from pants.util.contextutil import environment_as, pushd, temporary_dir


class ExpandPathTest(unittest.TestCase):
  def test_pure_relative(self):
    with self.root() as root:
      self.assertEquals(os.path.join(root, 'a'), expand_path('a'))

  def test_dot_relative(self):
    with self.root() as root:
      self.assertEquals(os.path.join(root, 'a'), expand_path('./a'))

  def test_absolute(self):
    self.assertEquals('/tmp/jake/bob', expand_path('/tmp/jake/bob'))

  def test_user_expansion(self):
    with environment_as(HOME='/tmp/jake'):
      self.assertEquals('/tmp/jake/bob', expand_path('~/bob'))

  def test_env_var_expansion(self):
    with self.root() as root:
      with environment_as(A='B', C='D'):
        self.assertEquals(os.path.join(root, 'B/D/E'), expand_path('$A/${C}/E'))

  @contextmanager
  def root(self):
    with temporary_dir() as root:
      # Avoid OSX issues where tmp dirs are reported as symlinks.
      real_root = os.path.realpath(root)
      with pushd(real_root):
        yield real_root
