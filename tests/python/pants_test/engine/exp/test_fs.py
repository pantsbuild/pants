# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from contextlib import contextmanager
from os.path import join

from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.engine.exp.fs import PathGlobs, PathLiteral, PathWildcard
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import touch


class FSTest(unittest.TestCase):

  @contextmanager
  def filesystem(self, *files):
    """Creates a ProjectTree containing the given files."""
    with temporary_dir() as d:
      for f in files:
        touch(join(d, f))
      yield FileSystemProjectTree(d)

  def pg(self, *pathglobs):
    return PathGlobs(pathglobs)

  def specs(self, relative_to, *filespecs):
    return PathGlobs.create_from_specs(relative_to, filespecs)

  def test_create_literal(self):
    name = 'Blah.java'
    self.assertEquals(self.pg(PathLiteral(name)), self.specs('', name))
    subdir = 'foo'
    self.assertEquals(self.pg(PathLiteral(join(subdir, name))), self.specs(subdir, name))

  def test_create_wildcard(self):
    name = '*.java'
    self.assertEquals(self.pg(PathWildcard('', name)), self.specs('', name))
    subdir = 'foo'
    self.assertEquals(self.pg(PathWildcard(subdir, name)), self.specs(subdir, name))
