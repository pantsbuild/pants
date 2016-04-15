# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from abc import abstractmethod

from pants.base.scm_project_tree import ScmProjectTree
from pants.engine.exp.fs import Dirs, FileContent, Files, Path, PathGlobs
from pants.scm.git import Git
from pants.util.meta import AbstractClass
from pants_test.engine.exp.scheduler_test_base import SchedulerTestBase


class FSTestBase(SchedulerTestBase, AbstractClass):

  _build_root_src = os.path.join(os.path.dirname(__file__), 'examples/fs_test')

  @abstractmethod
  def mk_project_tree(self, build_root_src):
    """Construct a ProjectTree for the given src path."""
    pass

  def specs(self, ftype, relative_to, *filespecs):
    return PathGlobs.create_from_specs(ftype, relative_to, filespecs)

  def assert_walk(self, ftype, filespecs, files):
    project_tree = self.mk_project_tree(self._build_root_src)
    scheduler, storage = self.mk_scheduler(project_tree=project_tree)
    result = self.execute(scheduler, storage, Path, self.specs(ftype, '', *filespecs))[0]
    self.assertEquals(set(files), set([p.path for p in result]))

  def assert_content(self, filespecs, expected_content):
    project_tree = self.mk_project_tree(self._build_root_src)
    scheduler, storage = self.mk_scheduler(project_tree=project_tree)
    result = self.execute(scheduler, storage, FileContent, self.specs(Files, '', *filespecs))[0]
    def validate(e):
      self.assertEquals(type(e), FileContent)
      return True
    actual_content = {f.path: f.content for f in result if validate(f)}
    self.assertEquals(expected_content, actual_content)

  def test_walk_literal(self):
    self.assert_walk(Files, ['4.txt'], ['4.txt'])
    self.assert_walk(Files, ['a/b/1.txt', 'a/b/2'], ['a/b/1.txt', 'a/b/2'])
    self.assert_walk(Files, ['c.ln/2'], ['c.ln/2'])
    self.assert_walk(Files, ['d.ln/b/1.txt'], ['d.ln/b/1.txt'])
    self.assert_walk(Files, ['a/3.txt'], ['a/3.txt'])
    self.assert_walk(Files, ['z.txt'], [])

  def test_walk_literal_directory(self):
    self.assert_walk(Dirs, ['c.ln'], ['a/b'])
    self.assert_walk(Dirs, ['a'], ['a'])
    self.assert_walk(Dirs, ['a/b'], ['a/b'])
    self.assert_walk(Dirs, ['z'], [])
    self.assert_walk(Dirs, ['4.txt', 'a/3.txt'], [])

  def test_walk_siblings(self):
    self.assert_walk(Files, ['*.txt'], ['4.txt'])
    self.assert_walk(Files, ['a/b/*.txt'], ['a/b/1.txt'])
    self.assert_walk(Files, ['c.ln/*.txt'], ['c.ln/1.txt'])
    self.assert_walk(Files, ['a/b/*'], ['a/b/1.txt', 'a/b/2'])
    self.assert_walk(Files, ['*/0.txt'], [])

  def test_walk_recursive(self):
    self.assert_walk(Files, ['**/*.txt.ln'], ['4.txt'])
    self.assert_walk(Files, ['**/*.txt'], ['a/3.txt', 'a/b/1.txt'])
    self.assert_walk(Files, ['*.txt', '**/*.txt'], ['a/3.txt', 'a/b/1.txt', '4.txt'])
    self.assert_walk(Files, ['*', '**/*'], ['a/3.txt', 'a/b/1.txt', '4.txt', 'a/b/2'])
    self.assert_walk(Files, ['**/*.zzz'], [])

  def test_walk_recursive_directory(self):
    self.assert_walk(Dirs, ['*'], ['a', 'a/b'])
    self.assert_walk(Dirs, ['*/*'], ['a/b'])
    self.assert_walk(Dirs, ['**/*'], ['a/b'])
    self.assert_walk(Dirs, ['*/*/*'], [])

  def test_files_content_literal(self):
    self.assert_content(['4.txt'], {'4.txt': 'four\n'})
    self.assert_content(['a/4.txt.ln'], {'4.txt': 'four\n'})

  def test_files_content_directory(self):
    with self.assertRaises(Exception):
      self.assert_content(['a/b/'], {'a/b/': 'nope\n'})
    with self.assertRaises(Exception):
      self.assert_content(['a/b'], {'a/b': 'nope\n'})


class PosixFSTest(unittest.TestCase, FSTestBase):

  def mk_project_tree(self, build_root_src):
    return self.mk_fs_tree(build_root_src)


# TODO: See https://github.com/pantsbuild/pants/issues/3189
@unittest.expectedFailure
class GitFSTest(unittest.TestCase, FSTestBase):

  def mk_project_tree(self, build_root_src):
    return ScmProjectTree(build_root_src, Git(worktree=build_root_src), 'HEAD')
