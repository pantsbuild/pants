# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from contextlib import contextmanager
from os.path import join

from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.engine.exp.fs import PathGlobs, PathLiteral, PathWildcard, PathDirWildcard
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

  def assert_pg_equals(self, pathglobs, relative_to, filespecs):
    self.assertEquals(self.pg(*pathglobs), self.specs(relative_to, *filespecs))

  def test_create_literal(self):
    subdir = 'foo'
    name = 'Blah.java'
    self.assert_pg_equals([PathLiteral(name)], '', [name])
    self.assert_pg_equals([PathLiteral(join(subdir, name))], subdir, [name])
    self.assert_pg_equals([PathLiteral(join(subdir, name))], '', [join(subdir, name)])

  def test_create_wildcard(self):
    name = '*.java'
    subdir = 'foo'
    self.assert_pg_equals([PathWildcard('', name)], '', [name])
    self.assert_pg_equals([PathWildcard(subdir, name)], subdir, [name])
    self.assert_pg_equals([PathWildcard(subdir, name)], '', [join(subdir, name)])

  def test_create_dir_wildcard(self):
    name = 'Blah.java'
    subdir = 'foo'
    wildcard = '*'
    self.assert_pg_equals([PathDirWildcard(subdir, wildcard, name)], '', [join(subdir, wildcard, name)])
    self.assert_pg_equals([PathDirWildcard(subdir, wildcard, name)], subdir, [join(wildcard, name)])
