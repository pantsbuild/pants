# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import tarfile
import unittest
from contextlib import contextmanager

from pants.base.project_tree import Dir, Link
from pants.engine.fs import FilesContent, PathGlobs, Snapshot
from pants.util.meta import AbstractClass
from pants_test.engine.scheduler_test_base import SchedulerTestBase


class DirectoryListing(object):
  """TODO: See #4027."""


class ReadLink(object):
  """TODO: See #4027."""


class FSTest(unittest.TestCase, SchedulerTestBase, AbstractClass):

  _original_src = os.path.join(os.path.dirname(__file__), 'examples/fs_test/fs_test.tar')

  @contextmanager
  def mk_project_tree(self, ignore_patterns=None):
    """Construct a ProjectTree for the given src path."""
    project_tree = self.mk_fs_tree(ignore_patterns=ignore_patterns)
    with tarfile.open(self._original_src) as tar:
      tar.extractall(project_tree.build_root)
    yield project_tree

  @staticmethod
  def specs(relative_to, *filespecs):
    return PathGlobs.create(relative_to, include=filespecs)

  def assert_walk_dirs(self, filespecs, paths, ignore_patterns=None):
    self.assert_walk_snapshot('dirs', filespecs, paths, ignore_patterns=ignore_patterns)

  def assert_walk_files(self, filespecs, paths, ignore_patterns=None):
    self.assert_walk_snapshot('files', filespecs, paths, ignore_patterns=ignore_patterns)

  def assert_walk_snapshot(self, field, filespecs, paths, ignore_patterns=None):
    with self.mk_project_tree(ignore_patterns=ignore_patterns) as project_tree:
      scheduler = self.mk_scheduler(project_tree=project_tree)
      result = self.execute(scheduler, Snapshot, self.specs('', *filespecs))[0]
      self.assertEquals(sorted([p.path for p in getattr(result, field)]), sorted(paths))

  def assert_content(self, filespecs, expected_content):
    with self.mk_project_tree() as project_tree:
      scheduler = self.mk_scheduler(project_tree=project_tree)
      result = self.execute(scheduler, FilesContent, self.specs('', *filespecs))[0]
      actual_content = {f.path: f.content for f in result.dependencies}
      self.assertEquals(expected_content, actual_content)

  def assert_digest(self, filespecs, expected_files):
    with self.mk_project_tree() as project_tree:
      scheduler = self.mk_scheduler(project_tree=project_tree)
      result = self.execute(scheduler, Snapshot, self.specs('', *filespecs))[0]
      # Confirm all expected files were digested.
      self.assertEquals(set(expected_files), set(f.path for f in result.files))
      self.assertTrue(result.fingerprint is not None)

  def assert_fsnodes(self, filespecs, subject_product_pairs):
    with self.mk_project_tree() as project_tree:
      scheduler = self.mk_scheduler(project_tree=project_tree)
      request = self.execute_request(scheduler, Snapshot, self.specs('', *filespecs))

      # Validate that FilesystemNodes for exactly the given subjects are reachable under this
      # request.
      fs_nodes = [n for n, _ in scheduler.product_graph.walk(roots=request.roots)
                  if type(n) is "TODO: need a new way to filter for FS intrinsics"]
      self.assertEquals(set((n.subject, n.product) for n in fs_nodes), set(subject_product_pairs))

  def test_walk_literal(self):
    self.assert_walk_files(['4.txt'], ['4.txt'])
    self.assert_walk_files(['a/b/1.txt', 'a/b/2'], ['a/b/1.txt', 'a/b/2'])
    self.assert_walk_files(['c.ln/2'], ['c.ln/2'])
    self.assert_walk_files(['d.ln/b/1.txt'], ['d.ln/b/1.txt'])
    self.assert_walk_files(['a/3.txt'], ['a/3.txt'])
    self.assert_walk_files(['z.txt'], [])

  def test_walk_literal_directory(self):
    self.assert_walk_dirs(['c.ln'], ['c.ln'])
    self.assert_walk_dirs(['a'], ['a'])
    self.assert_walk_dirs(['a/b'], ['a/b'])
    self.assert_walk_dirs(['z'], [])
    self.assert_walk_dirs(['4.txt', 'a/3.txt'], [])

  def test_walk_siblings(self):
    self.assert_walk_files(['*.txt'], ['4.txt'])
    self.assert_walk_files(['a/b/*.txt'], ['a/b/1.txt'])
    self.assert_walk_files(['c.ln/*.txt'], ['c.ln/1.txt'])
    self.assert_walk_files(['a/b/*'], ['a/b/1.txt', 'a/b/2'])
    self.assert_walk_files(['*/0.txt'], [])

  def test_walk_recursive(self):
    self.assert_walk_files(['**/*.txt.ln'], ['a/4.txt.ln', 'd.ln/4.txt.ln'])
    self.assert_walk_files(['**/*.txt'], ['4.txt',
                                           'a/3.txt',
                                           'a/b/1.txt',
                                           'c.ln/1.txt',
                                           'd.ln/3.txt',
                                           'd.ln/b/1.txt'])
    self.assert_walk_files(['**/*.txt'], ['a/3.txt',
                                           'a/b/1.txt',
                                           'c.ln/1.txt',
                                           'd.ln/3.txt',
                                           'd.ln/b/1.txt',
                                           '4.txt'])
    self.assert_walk_files(['**/3.t*t'], ['a/3.txt', 'd.ln/3.txt'])
    self.assert_walk_files(['**/*.zzz'], [])

  def test_walk_single_star(self):
    self.assert_walk_files(['*'], ['4.txt'])

  def test_walk_parent_link(self):
    self.assert_walk_files(['c.ln/../3.txt'], ['c.ln/../3.txt'])

  def test_walk_recursive_all(self):
    self.assert_walk_files(['**'], ['4.txt',
                                     'a/3.txt',
                                     'a/4.txt.ln',
                                     'a/b/1.txt',
                                     'a/b/2',
                                     'c.ln/1.txt',
                                     'c.ln/2',
                                     'd.ln/3.txt',
                                     'd.ln/4.txt.ln',
                                     'd.ln/b/1.txt',
                                     'd.ln/b/2'])

  def test_walk_ignore(self):
    # Ignore '*.ln' suffixed items at the root.
    self.assert_walk_files(['**'],
                           ['4.txt',
                            'a/3.txt',
                            'a/4.txt.ln',
                            'a/b/1.txt',
                            'a/b/2',],
                           ignore_patterns=['/*.ln'])
    # Whitelist one entry.
    self.assert_walk_files(['**'],
                           ['4.txt',
                            'a/3.txt',
                            'a/4.txt.ln',
                            'a/b/1.txt',
                            'a/b/2',
                            'c.ln/1.txt',
                            'c.ln/2',],
                           ignore_patterns=['/*.ln', '!c.ln'])

  def test_walk_recursive_trailing_doublestar(self):
    self.assert_walk_files(['a/**'], ['a/3.txt',
                                       'a/4.txt.ln',
                                       'a/b/1.txt',
                                       'a/b/2'])
    self.assert_walk_files(['d.ln/**'], ['d.ln/3.txt',
                                          'd.ln/4.txt.ln',
                                          'd.ln/b/1.txt',
                                          'd.ln/b/2'])
    self.assert_walk_dirs(['a/**'], ['a/b'])

  def test_walk_recursive_slash_doublestar_slash(self):
    self.assert_walk_files(['a/**/3.txt'], ['a/3.txt'])
    self.assert_walk_files(['a/**/b/1.txt'], ['a/b/1.txt'])
    self.assert_walk_files(['a/**/2'], ['a/b/2'])

  def test_walk_recursive_directory(self):
    self.assert_walk_dirs(['*'], ['a', 'c.ln', 'd.ln'])
    self.assert_walk_dirs(['*/*'], ['a/b', 'd.ln/b'])
    self.assert_walk_dirs(['**/*'], ['a', 'c.ln', 'd.ln', 'a/b', 'd.ln/b'])
    self.assert_walk_dirs(['*/*/*'], [])

  def test_remove_duplicates(self):
    self.assert_walk_files(['*', '**'], ['4.txt',
                                          'a/3.txt',
                                          'a/4.txt.ln',
                                          'a/b/1.txt',
                                          'a/b/2',
                                          'c.ln/1.txt',
                                          'c.ln/2',
                                          'd.ln/3.txt',
                                          'd.ln/4.txt.ln',
                                          'd.ln/b/1.txt',
                                          'd.ln/b/2'])
    self.assert_walk_files(['**/*.txt', 'a/b/1.txt', '4.txt'], ['4.txt',
                                                                 'a/3.txt',
                                                                 'c.ln/1.txt',
                                                                 'd.ln/3.txt',
                                                                 'a/b/1.txt',
                                                                 'd.ln/b/1.txt'])
    self.assert_walk_dirs(['*', '**'], ['a', 'c.ln', 'd.ln', 'a/b', 'd.ln/b'])

  def test_files_content_literal(self):
    self.assert_content(['4.txt', 'a/4.txt.ln'], {'4.txt': 'four\n', 'a/4.txt.ln': 'four\n'})

  def test_files_content_directory(self):
    with self.assertRaises(Exception):
      self.assert_content(['a/b/'], {'a/b/': 'nope\n'})
    with self.assertRaises(Exception):
      self.assert_content(['a/b'], {'a/b': 'nope\n'})

  def test_files_content_symlink(self):
    self.assert_content(['c.ln/../3.txt'], {'c.ln/../3.txt': 'three\n'})

  def test_files_digest_literal(self):
    self.assert_digest(['a/3.txt', '4.txt'], ['a/3.txt', '4.txt'])

  @unittest.skip('Skipped to expedite landing #3821; see: #4027.')
  def test_nodes_file(self):
    self.assert_fsnodes(['4.txt'], [
        (Dir(''), DirectoryListing),
      ])

  @unittest.skip('Skipped to expedite landing #3821; see: #4027.')
  def test_nodes_symlink_file(self):
    self.assert_fsnodes(['c.ln/2'], [
        (Dir(''), DirectoryListing),
        (Link('c.ln'), ReadLink),
        (Dir('a'), DirectoryListing),
        (Dir('a/b'), DirectoryListing),
      ])
    self.assert_fsnodes(['d.ln/b/1.txt'], [
        (Dir(''), DirectoryListing),
        (Link('d.ln'), ReadLink),
        (Dir('a'), DirectoryListing),
        (Dir('a/b'), DirectoryListing),
      ])

  @unittest.skip('Skipped to expedite landing #3821; see: #4027.')
  def test_nodes_symlink_globbed_dir(self):
    self.assert_fsnodes(['*/2'], [
        # Scandir for the root.
        (Dir(''), DirectoryListing),
        # Read links to determine whether they're actually directories.
        (Link('c.ln'), ReadLink),
        (Link('d.ln'), ReadLink),
        # Scan second level destinations: `a/b` is matched via `c.ln`.
        (Dir('a'), DirectoryListing),
        (Dir('a/b'), DirectoryListing),
      ])

  @unittest.skip('Skipped to expedite landing #3821; see: #4027.')
  def test_nodes_symlink_globbed_file(self):
    self.assert_fsnodes(['d.ln/b/*.txt'], [
        # NB: Needs to scandir every Dir on the way down to track whether
        # it is traversing a symlink.
        (Dir(''), DirectoryListing),
        # Traverse one symlink.
        (Link('d.ln'), ReadLink),
        (Dir('a'), DirectoryListing),
        (Dir('a/b'), DirectoryListing),
      ])
