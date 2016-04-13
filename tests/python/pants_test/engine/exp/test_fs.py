# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from os.path import join

from pants.engine.exp.fs import (FileContent, Files, Dirs, Path, PathDirWildcard, PathGlobs,
                                 PathWildcard)
from pants_test.engine.exp.scheduler_test_base import SchedulerTestBase


class FSTest(unittest.TestCase, SchedulerTestBase):

  _build_root_src = os.path.join(os.path.dirname(__file__), 'examples/fs_test')

  def specs(self, ftype, relative_to, *filespecs):
    return PathGlobs.create_from_specs(ftype, relative_to, filespecs)

  def assert_walk(self, ftype, filespecs, files):
    scheduler, storage, _ = self.mk_scheduler(build_root_src=self._build_root_src)
    result = self.execute(scheduler, storage, Path, self.specs(ftype, '', *filespecs))[0]
    self.assertEquals(set(files), set([p.path for p in result]))

  def assert_content(self, filespecs, expected_content):
    scheduler, storage, _ = self.mk_scheduler(build_root_src=self._build_root_src)
    result = self.execute(scheduler, storage, FileContent, self.specs(Files, '', *filespecs))[0]
    def validate(e):
      self.assertEquals(type(e), FileContent)
      return True
    actual_content = {f.path: f.content for f in result if validate(f)}
    self.assertEquals(expected_content, actual_content)

  def assert_pg_equals(self, ftype, pathglobs, relative_to, filespecs):
    self.assertEquals(PathGlobs(ftype, tuple(pathglobs)), self.specs(ftype, relative_to, *filespecs))

  def assert_files_equals(self, pathglobs, relative_to, filespecs):
    self.assert_pg_equals(Files, pathglobs, relative_to, filespecs)

  def assert_dirs_equals(self, pathglobs, relative_to, filespecs):
    self.assert_pg_equals(Dirs, pathglobs, relative_to, filespecs)

  def test_create_literal(self):
    subdir = 'foo'
    name = 'Blah.java'
    self.assert_files_equals([Path(name)], '', [name])
    self.assert_files_equals([Path(join(subdir, name))], subdir, [name])
    self.assert_files_equals([Path(join(subdir, name))], '', [join(subdir, name)])

  def test_create_literal_directory(self):
    subdir = 'foo'
    name = 'bar/.'
    self.assert_dirs_equals([Path(name)], '', [name])
    self.assert_dirs_equals([Path(join(subdir, name))], subdir, [name])
    self.assert_dirs_equals([Path(join(subdir, name))], '', [join(subdir, name)])

  def test_create_wildcard(self):
    name = '*.java'
    subdir = 'foo'
    self.assert_files_equals([PathWildcard(Files, '', name)], '', [name])
    self.assert_files_equals([PathWildcard(Files, subdir, name)], subdir, [name])
    self.assert_files_equals([PathWildcard(Files, subdir, name)], '', [join(subdir, name)])

  def test_create_dir_wildcard(self):
    name = 'Blah.java'
    subdir = 'foo'
    wildcard = '*'
    self.assert_files_equals([PathDirWildcard(Files, subdir, wildcard, (name,))],
                             '',
                             [join(subdir, wildcard, name)])
    self.assert_files_equals([PathDirWildcard(Files, subdir, wildcard, (name,))],
                             subdir,
                             [join(wildcard, name)])

  def test_create_dir_wildcard_directory(self):
    subdir = 'foo'
    wildcard = '*'
    name = '.'
    self.assert_dirs_equals([PathDirWildcard(Dirs, '', wildcard, (name,))],
                            '',
                            [join(wildcard, name)])
    self.assert_dirs_equals([PathDirWildcard(Dirs, subdir, wildcard, (name,))],
                            subdir,
                            [join(wildcard, name)])

  def test_create_recursive_dir_wildcard(self):
    name = 'Blah.java'
    subdir = 'foo'
    wildcard = '**'
    expected_remainders = (name, join(wildcard, name))
    self.assert_files_equals([PathDirWildcard(Files, subdir, wildcard, expected_remainders)],
                             '',
                             [join(subdir, wildcard, name)])
    self.assert_files_equals([PathDirWildcard(Files, subdir, wildcard, expected_remainders)],
                             subdir,
                             [join(wildcard, name)])

  def test_walk_literal(self):
    self.assert_walk(Files, ['4.txt'], ['4.txt'])
    self.assert_walk(Files, ['a/b/1.txt', 'a/b/2'], ['a/b/1.txt', 'a/b/2'])
    self.assert_walk(Files, ['a/3.txt'], ['a/3.txt'])
    self.assert_walk(Files, ['z.txt'], [])

  def test_walk_literal_directory(self):
    self.assert_walk(Dirs, ['a/'], ['a'])
    self.assert_walk(Dirs, ['a/b/'], ['a/b'])
    self.assert_walk(Dirs, ['z/'], [])
    self.assert_walk(Dirs, ['4.txt', 'a/3.txt'], [])

  def test_walk_siblings(self):
    self.assert_walk(Files, ['*.txt'], ['4.txt'])
    self.assert_walk(Files, ['a/b/*.txt'], ['a/b/1.txt'])
    self.assert_walk(Files, ['a/b/*'], ['a/b/1.txt', 'a/b/2'])
    self.assert_walk(Files, ['*/0.txt'], [])

  def test_walk_recursive(self):
    self.assert_walk(Files, ['**/*.txt'], ['a/3.txt', 'a/b/1.txt'])
    self.assert_walk(Files, ['*.txt', '**/*.txt'], ['a/3.txt', 'a/b/1.txt', '4.txt'])
    self.assert_walk(Files, ['*', '**/*'], ['a/3.txt', 'a/b/1.txt', '4.txt', 'a/4.txt.ln', 'a/b/2'])
    self.assert_walk(Files, ['**/*.zzz'], [])

  def test_walk_recursive_directory(self):
    self.assert_walk(Dirs, ['*/.'], ['a'])
    self.assert_walk(Dirs, ['*/*/.'], ['a/b'])
    self.assert_walk(Dirs, ['**/*/.'], ['a/b'])
    self.assert_walk(Dirs, ['*/*/*/.'], [])

  def test_files_content_literal(self):
    self.assert_content(['4.txt'], {'4.txt': 'four\n'})

  def test_files_content_directory(self):
    with self.assertRaises(Exception):
      self.assert_content(['a/b/'], {'a/b/': 'nope\n'})
    with self.assertRaises(Exception):
      self.assert_content(['a/b'], {'a/b': 'nope\n'})
