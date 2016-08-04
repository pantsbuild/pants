# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from os.path import join

from pants.base.project_tree import Dir
from pants.engine.fs import PathDirWildcard, PathGlobs, PathRoot, PathWildcard


def pw(relative_to, *args):
  return PathWildcard(Dir(relative_to), relative_to, *args)


def pdw(relative_to, *args):
  return PathDirWildcard(Dir(relative_to), relative_to, *args)


class PathGlobsTest(unittest.TestCase):

  def assert_pg_equals(self, pathglobs, relative_to, filespecs):
    self.assertEquals(PathGlobs(tuple(pathglobs)), PathGlobs.create_from_specs(relative_to, filespecs))

  def test_root(self):
    self.assert_pg_equals([PathRoot()], '', [''])

  def test_literal(self):
    subdir = 'foo'
    name = 'Blah.java'
    self.assert_pg_equals([pw('', name)], '', [name])
    self.assert_pg_equals([pw(subdir, name)], subdir, [name])
    self.assert_pg_equals([pdw('', subdir, name)], '', [join(subdir, name)])

  def test_wildcard(self):
    name = '*.java'
    subdir = 'foo'
    self.assert_pg_equals([pw('', name)], '', [name])
    self.assert_pg_equals([pw(subdir, name)], subdir, [name])

  def test_dir_wildcard(self):
    name = 'Blah.java'
    subdir = 'foo'
    wildcard = '*'
    self.assert_pg_equals([pdw(subdir, wildcard, name)],
                          subdir,
                          [join(wildcard, name)])

  def test_dir_wildcard_directory(self):
    subdir = 'foo'
    wildcard = '*'
    name = '.'
    self.assert_pg_equals([pw('', wildcard)],
                          '',
                          [join(wildcard, name)])
    self.assert_pg_equals([pw(subdir, wildcard)],
                          subdir,
                          [join(wildcard, name)])

  def test_recursive_dir_wildcard(self):
    name = 'Blah.java'
    subdir = 'foo'
    wildcard = '**'
    self.assert_pg_equals([pdw(subdir, '*', join(wildcard, name)), pw(subdir, name)],
                          subdir,
                          [join(wildcard, name)])

  def test_trailing_doublestar(self):
    subdir = 'foo'
    wildcard = '**'
    self.assert_pg_equals([pdw(subdir, '*', wildcard), pw(subdir, '*')],
                          subdir,
                          [wildcard])

  def test_doublestar_mixed_wildcard(self):
    subdir = 'foo'
    wildcard = '**abc'
    name = 'Blah.java'

    self.assert_pg_equals([pw(subdir, wildcard)], subdir, [wildcard])
    self.assert_pg_equals([pdw(subdir, wildcard, name)], subdir, [join(wildcard, name)])
