# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from os.path import join

from pants.engine.exp.fs import (FileContent, Path, PathDirWildcard, PathGlobs, PathLiteral,
                                 PathWildcard)
from pants_test.engine.exp.scheduler_test_base import SchedulerTestBase


class FSTest(unittest.TestCase, SchedulerTestBase):

  _build_root_src = os.path.join(os.path.dirname(__file__), 'examples/fs_test')

  def pg(self, *pathglobs):
    return PathGlobs(pathglobs)

  def specs(self, relative_to, *filespecs):
    return PathGlobs.create_from_specs(relative_to, filespecs)

  def assert_walk(self, filespecs, files):
    scheduler, storage, _ = self.mk_scheduler(build_root_src=self._build_root_src)
    result = self.execute(scheduler, storage, Path, self.specs('', *filespecs))[0]
    self.assertEquals(set(files), set([p.path for p in result]))

  def assert_content(self, filespecs, expected_content):
    scheduler, storage, _ = self.mk_scheduler(build_root_src=self._build_root_src)
    result = self.execute(scheduler, storage, FileContent, self.specs('', *filespecs))[0]
    def validate(e):
      self.assertEquals(type(e), FileContent)
      return True
    actual_content = {f.path: f.content for f in result if validate(f)}
    self.assertEquals(expected_content, actual_content)

  def assert_pg_equals(self, pathglobs, relative_to, filespecs):
    self.assertEquals(self.pg(*pathglobs), self.specs(relative_to, *filespecs))

  def test_create_literal(self):
    subdir = 'foo'
    name = 'Blah.java'
    self.assert_pg_equals([PathLiteral(name)], '', [name])
    self.assert_pg_equals([PathLiteral(join(subdir, name))], subdir, [name])
    self.assert_pg_equals([PathLiteral(join(subdir, name))], '', [join(subdir, name)])

  def test_create_literal_directory(self):
    subdir = 'foo'
    name = 'bar/'
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
    self.assert_pg_equals([PathDirWildcard(subdir, wildcard, (name,))],
                          '',
                          [join(subdir, wildcard, name)])
    self.assert_pg_equals([PathDirWildcard(subdir, wildcard, (name,))],
                          subdir,
                          [join(wildcard, name)])

  def test_create_recursive_dir_wildcard(self):
    name = 'Blah.java'
    subdir = 'foo'
    wildcard = '**'
    expected_remainders = (name, join(wildcard, name))
    self.assert_pg_equals([PathDirWildcard(subdir, wildcard, expected_remainders)],
                          '',
                          [join(subdir, wildcard, name)])
    self.assert_pg_equals([PathDirWildcard(subdir, wildcard, expected_remainders)],
                          subdir,
                          [join(wildcard, name)])

  def test_walk_literal(self):
    self.assert_walk(['4.txt'], ['4.txt'])
    self.assert_walk(['a/b/1.txt', 'a/b/2'], ['a/b/1.txt', 'a/b/2'])
    self.assert_walk(['a/3.txt'], ['a/3.txt'])
    self.assert_walk(['z.txt'], [])

  def test_walk_literal_directory(self):
    self.assert_walk(['a/'], ['a/'])
    self.assert_walk(['a/b/'], ['a/b/'])
    self.assert_walk(['z/'], [])

  def test_walk_siblings(self):
    self.assert_walk(['*.txt'], ['4.txt'])
    self.assert_walk(['a/b/*.txt'], ['a/b/1.txt'])
    self.assert_walk(['a/b/*'], ['a/b/1.txt', 'a/b/2'])
    self.assert_walk(['*/0.txt'], [])

  def test_walk_recursive(self):
    self.assert_walk(['**/*.txt'], ['a/3.txt', 'a/b/1.txt'])
    self.assert_walk(['*.txt', '**/*.txt'], ['a/3.txt', 'a/b/1.txt', '4.txt'])
    self.assert_walk(['*', '**/*'], ['a/3.txt', 'a/b/1.txt', '4.txt', 'a/b/2'])
    self.assert_walk(['**/*.zzz'], [])

  def test_files_content_literal(self):
    self.assert_content(['4.txt'], {'4.txt': 'four\n'})
