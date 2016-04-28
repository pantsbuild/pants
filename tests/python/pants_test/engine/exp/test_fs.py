# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
import unittest
from abc import abstractmethod
from contextlib import contextmanager

from pants.base.scm_project_tree import ScmProjectTree
from pants.engine.exp.fs import (Dir, DirectoryListing, Dirs, FileContent, Files, Link, Path,
                                 PathGlobs, ReadLink, Stat, Stats)
from pants.engine.exp.nodes import FilesystemNode
from pants.scm.git import Git
from pants.util.contextutil import environment_as
from pants.util.dirutil import safe_mkdtemp, safe_rmtree
from pants.util.meta import AbstractClass
from pants_test.engine.exp.scheduler_test_base import SchedulerTestBase
from pants_test.testutils.git_util import Version, git_version


class FSTestBase(SchedulerTestBase, AbstractClass):

  _original_src = os.path.join(os.path.dirname(__file__), 'examples/fs_test')

  @abstractmethod
  @contextmanager
  def mk_project_tree(self, build_root_src):
    """Construct a ProjectTree for the given src path."""
    pass

  def specs(self, ftype, relative_to, *filespecs):
    return PathGlobs.create_from_specs(ftype, relative_to, filespecs)

  def assert_walk(self, ftype, filespecs, files):
    with self.mk_project_tree(self._original_src) as project_tree:
      scheduler, storage = self.mk_scheduler(project_tree=project_tree)
      result = self.execute(scheduler, storage, Stat, self.specs(ftype, '', *filespecs))[0]
      self.assertEquals(set(files), set([p.path for p in result]))

  def assert_content(self, filespecs, expected_content):
    with self.mk_project_tree(self._original_src) as project_tree:
      scheduler, storage = self.mk_scheduler(project_tree=project_tree)
      result = self.execute(scheduler, storage, FileContent, self.specs(Files, '', *filespecs))[0]
      def validate(e):
        self.assertEquals(type(e), FileContent)
        return True
      actual_content = {f.path: f.content for f in result if validate(f)}
      self.assertEquals(expected_content, actual_content)

  def assert_fsnodes(self, ftype, filespecs, subject_product_pairs):
    with self.mk_project_tree(self._original_src) as project_tree:
      scheduler, storage = self.mk_scheduler(project_tree=project_tree)
      request = self.execute_request(scheduler, storage, Stat, self.specs(ftype, '', *filespecs))

      # Validate that FilesystemNodes for exactly the given subjects are reachable under this
      # request.
      fs_nodes = [n for ((n, _), _) in scheduler.product_graph.walk(roots=request.roots)
                  if type(n) is FilesystemNode]
      self.assertEquals(set((n.subject, n.product) for n in fs_nodes), set(subject_product_pairs))

  def test_walk_literal(self):
    self.assert_walk(Files, ['4.txt'], ['4.txt'])
    self.assert_walk(Files, ['a/b/1.txt', 'a/b/2'], ['a/b/1.txt', 'a/b/2'])
    self.assert_walk(Files, ['c.ln/2'], ['a/b/2'])
    self.assert_walk(Files, ['d.ln/b/1.txt'], ['a/b/1.txt'])
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
    self.assert_walk(Files, ['c.ln/*.txt'], ['a/b/1.txt'])
    self.assert_walk(Files, ['a/b/*'], ['a/b/1.txt', 'a/b/2'])
    self.assert_walk(Files, ['*/0.txt'], [])

  @unittest.skip('https://github.com/pantsbuild/pants/issues/3281')
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

  @unittest.skip('https://github.com/pantsbuild/pants/issues/3281')
  def test_files_content_literal(self):
    self.assert_content(['4.txt'], {'4.txt': 'four\n'})
    self.assert_content(['a/4.txt.ln'], {'4.txt': 'four\n'})

  def test_files_content_directory(self):
    with self.assertRaises(Exception):
      self.assert_content(['a/b/'], {'a/b/': 'nope\n'})
    with self.assertRaises(Exception):
      self.assert_content(['a/b'], {'a/b': 'nope\n'})

  def test_nodes_file(self):
    self.assert_fsnodes(Files, ['4.txt'], [
        (Path('4.txt'), Stats),
      ])

  def test_nodes_symlink_file(self):
    self.assert_fsnodes(Files, ['c.ln/2'], [
        (Link('c.ln'), ReadLink),
        (Path('c.ln'), Stats),
        (Path('a/b'), Stats),
        (Path('a/b/2'), Stats),
      ])
    self.assert_fsnodes(Files, ['d.ln/b/1.txt'], [
        (Path('d.ln'), Stats),
        (Link('d.ln'), ReadLink),
        (Path('a'), Stats),
        (Path('a/b'), Stats),
        (Path('a/b/1.txt'), Stats),
      ])

  def test_nodes_symlink_globbed_dir(self):
    self.assert_fsnodes(Files, ['*/2'], [
        # Glob the root.
        (Dir(''), DirectoryListing),
        # Stat each entry.
        (Path('a'), Stats),
        (Path('c.ln'), Stats),
        (Path('d.ln'), Stats),
        (Path('4.txt'), Stats),
        # Read links to determine whether they're actually directories.
        (Link('c.ln'), ReadLink),
        (Link('d.ln'), ReadLink),
        # Stat the detination of one link (the other was already stat'd during the initial list).
        (Path('a/b'), Stats),
        # Look up the literal in each path.
        (Path('a/b/2'), Stats),
        (Path('a/2'), Stats),
      ])

  def test_nodes_symlink_globbed_file(self):
    self.assert_fsnodes(Files, ['d.ln/b/*.txt'], [
        # NB: Needs to stat every path on the way down to track whether
        # it is traversing a symlink.
        (Path('d.ln'), Stats),
        (Link('d.ln'), ReadLink),
        (Path('a'), Stats),
        (Path('a/b'), Stats),
        (Dir('a/b'), DirectoryListing),
        (Path('a/b/2'), Stats),
        (Path('a/b/1.txt'), Stats),
      ])


class PosixFSTest(unittest.TestCase, FSTestBase):

  @contextmanager
  def mk_project_tree(self, build_root_src):
    yield self.mk_fs_tree(build_root_src)


@unittest.skipIf(git_version() < Version('1.7.10'), 'The GitTest requires git >= 1.7.10.')
class GitFSTest(unittest.TestCase, FSTestBase):

  @contextmanager
  def mk_project_tree(self, build_root_src):
    gitdir = safe_mkdtemp()

    # Use mk_fs_tree only to feed the files for the git repo, not using its FileSystemProjectTree.
    worktree = self.mk_fs_tree(build_root_src).build_root
    with environment_as(GIT_DIR=gitdir, GIT_WORK_TREE=worktree):
      subprocess.check_call(['git', 'init'])
      subprocess.check_call(['git', 'config', 'user.email', 'you@example.com'])
      subprocess.check_call(['git', 'config', 'user.name', 'Your Name'])
      for file in ['4.txt', 'a', 'c.ln', 'd.ln']:
        subprocess.check_call(['git', 'add', file])
      subprocess.check_call(['git', 'commit', '-am', 'Add project files.'])

      yield ScmProjectTree(worktree, Git(gitdir=gitdir, worktree=worktree), 'HEAD')

    safe_rmtree(gitdir)
    safe_rmtree(worktree)
