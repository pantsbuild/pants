# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from os.path import join

from pants.engine.fs import Dirs, Path, PathDirWildcard, PathGlobs, PathWildcard


class PathGlobsTest(unittest.TestCase):

  def assert_pg_equals(self, pathglobs, relative_to, filespecs):
    self.assertEquals(PathGlobs(tuple(pathglobs)), PathGlobs.create_from_specs(relative_to, filespecs))

  def test_literal(self):
    subdir = 'foo'
    name = 'Blah.java'
    self.assert_pg_equals([Path(name)], '', [name])
    self.assert_pg_equals([Path(join(subdir, name))], subdir, [name])
    self.assert_pg_equals([PathDirWildcard(subdir, name)], '', [join(subdir, name)])

  def test_wildcard(self):
    name = '*.java'
    subdir = 'foo'
    self.assert_pg_equals([PathWildcard('', name)], '', [name])
    self.assert_pg_equals([PathWildcard(subdir, name)], subdir, [name])

  def test_dir_wildcard(self):
    name = 'Blah.java'
    subdir = 'foo'
    wildcard = '*'
    self.assert_pg_equals([PathDirWildcard(subdir, wildcard, (name,))],
                          subdir,
                          [join(wildcard, name)])

  def test_dir_wildcard_directory(self):
    subdir = 'foo'
    wildcard = '*'
    name = '.'
    self.assert_pg_equals([PathDirWildcard(Dirs, '', wildcard, (name,))],
                          '',
                          [join(wildcard, name)])
    self.assert_pg_equals([PathDirWildcard(Dirs, subdir, wildcard, (name,))],
                          subdir,
                          [join(wildcard, name)])

  def test_recursive_dir_wildcard(self):
    name = 'Blah.java'
    subdir = 'foo'
    wildcard = '**'
    expected_remainders = (name, join(wildcard, name))
    self.assert_pg_equals([PathDirWildcard(subdir, wildcard, expected_remainders)],
                          subdir,
                          [join(wildcard, name)])
