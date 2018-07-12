# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
import tarfile
import unittest
from builtins import object, str
from contextlib import contextmanager

from future.utils import text_type

from pants.base.project_tree import Dir, Link
from pants.engine.fs import (EMPTY_DIRECTORY_DIGEST, DirectoryDigest, DirectoryToMaterialize,
                             FilesContent, PathGlobs, PathGlobsAndRoot, Snapshot, create_fs_rules)
from pants.util.contextutil import temporary_dir
from pants.util.meta import AbstractClass
from pants_test.engine.scheduler_test_base import SchedulerTestBase
from pants_test.test_base import TestBase


class DirectoryListing(object):
  """TODO: See #4027."""


class ReadLink(object):
  """TODO: See #4027."""


class FSTest(TestBase, SchedulerTestBase, AbstractClass):

  _original_src = os.path.join(os.path.dirname(__file__), 'examples/fs_test/fs_test.tar')

  @contextmanager
  def mk_project_tree(self, ignore_patterns=None):
    """Construct a ProjectTree for the given src path."""
    project_tree = self.mk_fs_tree(ignore_patterns=ignore_patterns)
    with tarfile.open(self._original_src) as tar:
      tar.extractall(project_tree.build_root)
    yield project_tree

  @staticmethod
  def specs(filespecs):
    if isinstance(filespecs, PathGlobs):
      return filespecs
    else:
      return PathGlobs(include=filespecs)

  def assert_walk_dirs(self, filespecs_or_globs, paths, ignore_patterns=None):
    self.assert_walk_snapshot('dirs', filespecs_or_globs, paths, ignore_patterns=ignore_patterns)

  def assert_walk_files(self, filespecs_or_globs, paths, ignore_patterns=None):
    self.assert_walk_snapshot('files', filespecs_or_globs, paths, ignore_patterns=ignore_patterns)

  def assert_walk_snapshot(self, field, filespecs_or_globs, paths, ignore_patterns=None):
    with self.mk_project_tree(ignore_patterns=ignore_patterns) as project_tree:
      scheduler = self.mk_scheduler(rules=create_fs_rules(), project_tree=project_tree)
      result = self.execute(scheduler, Snapshot, self.specs(filespecs_or_globs))[0]
      self.assertEquals(sorted([p.path for p in getattr(result, field)]), sorted(paths))

  def assert_content(self, filespecs_or_globs, expected_content):
    with self.mk_project_tree() as project_tree:
      scheduler = self.mk_scheduler(rules=create_fs_rules(), project_tree=project_tree)
      snapshot = self.execute_expecting_one_result(scheduler, Snapshot, self.specs(filespecs_or_globs)).value
      result = self.execute_expecting_one_result(scheduler, FilesContent, snapshot.directory_digest).value
      actual_content = {f.path: f.content for f in result.dependencies}
      self.assertEquals(expected_content, actual_content)

  def assert_digest(self, filespecs_or_globs, expected_files):
    with self.mk_project_tree() as project_tree:
      scheduler = self.mk_scheduler(rules=create_fs_rules(), project_tree=project_tree)
      result = self.execute(scheduler, Snapshot, self.specs(filespecs_or_globs))[0]
      # Confirm all expected files were digested.
      self.assertEquals(set(expected_files), set(f.path for f in result.files))
      self.assertTrue(result.directory_digest.fingerprint is not None)

  def assert_fsnodes(self, filespecs_or_globs, subject_product_pairs):
    with self.mk_project_tree() as project_tree:
      scheduler = self.mk_scheduler(rules=create_fs_rules(), project_tree=project_tree)
      request = self.execute_request(scheduler, Snapshot, self.specs(filespecs_or_globs))

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

  def test_snapshot_from_outside_buildroot(self):
    with temporary_dir() as temp_dir:
      with open(os.path.join(temp_dir, "roland"), "w") as f:
        f.write("European Burmese")
      scheduler = self.mk_scheduler(rules=create_fs_rules())
      globs = PathGlobs(("*",), ())
      snapshot = scheduler.capture_snapshots((PathGlobsAndRoot(globs, text_type(temp_dir)),))[0]
      self.assert_snapshot_equals(snapshot, ["roland"], DirectoryDigest(
        text_type("63949aa823baf765eff07b946050d76ec0033144c785a94d3ebd82baa931cd16"),
        80
      ))

  def test_multiple_snapshots_from_outside_buildroot(self):
    with temporary_dir() as temp_dir:
      with open(os.path.join(temp_dir, "roland"), "w") as f:
        f.write("European Burmese")
      with open(os.path.join(temp_dir, "susannah"), "w") as f:
        f.write("I don't know")
      scheduler = self.mk_scheduler(rules=create_fs_rules())
      snapshots = scheduler.capture_snapshots((
        PathGlobsAndRoot(PathGlobs(("roland",), ()), text_type(temp_dir)),
        PathGlobsAndRoot(PathGlobs(("susannah",), ()), text_type(temp_dir)),
        PathGlobsAndRoot(PathGlobs(("doesnotexist",), ()), text_type(temp_dir)),
      ))
      self.assertEquals(3, len(snapshots))
      self.assert_snapshot_equals(snapshots[0], ["roland"], DirectoryDigest(
        text_type("63949aa823baf765eff07b946050d76ec0033144c785a94d3ebd82baa931cd16"),
        80
      ))
      self.assert_snapshot_equals(snapshots[1], ["susannah"], DirectoryDigest(
        text_type("d3539cfc21eb4bab328ca9173144a8e932c515b1b9e26695454eeedbc5a95f6f"),
        82
      ))
      self.assert_snapshot_equals(snapshots[2], [], EMPTY_DIRECTORY_DIGEST)

  def test_snapshot_from_outside_buildroot_failure(self):
    with temporary_dir() as temp_dir:
      scheduler = self.mk_scheduler(rules=create_fs_rules())
      globs = PathGlobs(("*",), ())
      with self.assertRaises(Exception) as cm:
        scheduler.capture_snapshots((PathGlobsAndRoot(globs, text_type(os.path.join(temp_dir, "doesnotexist"))),))
      self.assertIn("doesnotexist", str(cm.exception))

  def assert_snapshot_equals(self, snapshot, files, directory_digest):
    self.assertEquals([file.path for file in snapshot.files], files)
    self.assertEquals(snapshot.directory_digest, directory_digest)

  def test_merge_zero_directories(self):
    scheduler = self.mk_scheduler(rules=create_fs_rules())
    dir = scheduler.merge_directories(())
    self.assertEqual(EMPTY_DIRECTORY_DIGEST, dir)

  def test_merge_directories(self):
    with temporary_dir() as temp_dir:
      with open(os.path.join(temp_dir, "roland"), "w") as f:
        f.write("European Burmese")
      with open(os.path.join(temp_dir, "susannah"), "w") as f:
        f.write("Not sure actually")
      scheduler = self.mk_scheduler(rules=create_fs_rules())
      (empty_snapshot, roland_snapshot, susannah_snapshot, both_snapshot) = (
          scheduler.capture_snapshots((
            PathGlobsAndRoot(PathGlobs(("doesnotmatch",), ()), text_type(temp_dir)),
            PathGlobsAndRoot(PathGlobs(("roland",), ()), text_type(temp_dir)),
            PathGlobsAndRoot(PathGlobs(("susannah",), ()), text_type(temp_dir)),
            PathGlobsAndRoot(PathGlobs(("*",), ()), text_type(temp_dir)),
        ))
      )

      empty_merged = scheduler.merge_directories((empty_snapshot.directory_digest))
      self.assertEquals(
        empty_snapshot.directory_digest,
        empty_merged,
      )

      roland_merged = scheduler.merge_directories((
        roland_snapshot.directory_digest,
        empty_snapshot.directory_digest,
      ))
      self.assertEquals(
        roland_snapshot.directory_digest,
        roland_merged,
      )

      both_merged = scheduler.merge_directories((
        roland_snapshot.directory_digest,
        susannah_snapshot.directory_digest,
      ))

      self.assertEquals(both_snapshot.directory_digest, both_merged)

  def test_materialize_directories(self):
    # I tried passing in the digest of a file, but it didn't make it to the
    # rust code due to all of the checks we have in place (which is probably a good thing).
    self.prime_store_with_roland_digest()

    with temporary_dir() as temp_dir:
      dir_path = os.path.join(temp_dir, "containing_roland")
      digest = DirectoryDigest(
        text_type("63949aa823baf765eff07b946050d76ec0033144c785a94d3ebd82baa931cd16"),
        80
      )
      scheduler = self.mk_scheduler(rules=create_fs_rules())
      scheduler.materialize_directories((DirectoryToMaterialize(text_type(dir_path), digest),))

      created_file = os.path.join(dir_path, "roland")
      with open(created_file) as f:
        content = f.read()
        self.assertEquals(content, "European Burmese")

  def test_glob_match_error(self):
    with self.assertRaises(ValueError) as cm:
      self.assert_walk_files(PathGlobs(
        include=['not-a-file.txt'],
        exclude=[],
        glob_match_error_behavior='error',
      ), [])
    expected_msg = (
      "Globs did not match. Excludes were: []. Unmatched globs were: [\"not-a-file.txt\"].")
    self.assertIn(expected_msg, str(cm.exception))

  def test_glob_match_exclude_error(self):
    with self.assertRaises(ValueError) as cm:
      self.assert_walk_files(PathGlobs(
        include=['*.txt'],
        exclude=['4.txt'],
        glob_match_error_behavior='error',
      ), [])
    expected_msg = (
      "Globs did not match. Excludes were: [\"4.txt\"]. Unmatched globs were: [\"*.txt\"].")
    self.assertIn(expected_msg, str(cm.exception))

  def test_glob_match_ignore_logging(self):
    with self.captured_logging(logging.WARNING) as captured:
      self.assert_walk_files(PathGlobs(
        include=['not-a-file.txt'],
        exclude=[''],
        glob_match_error_behavior='ignore',
      ), [])
      self.assertEqual(0, len(captured.warnings()))

  @unittest.skip('Skipped to expedite landing #5769: see #5863')
  def test_glob_match_warn_logging(self):
    with self.captured_logging(logging.WARNING) as captured:
      self.assert_walk_files(PathGlobs(
        include=['not-a-file.txt'],
        exclude=[''],
        glob_match_error_behavior='warn',
      ), [])
      all_warnings = captured.warnings()
      self.assertEqual(1, len(all_warnings))
      single_warning = all_warnings[0]
      self.assertEqual("???", str(single_warning))

  def prime_store_with_roland_digest(self):
    """This method primes the store with a directory of a file named 'roland' and contents 'European Burmese'."""
    with temporary_dir() as temp_dir:
      with open(os.path.join(temp_dir, "roland"), "w") as f:
        f.write("European Burmese")
      scheduler = self.mk_scheduler(rules=create_fs_rules())
      globs = PathGlobs(("*",), ())
      snapshot = scheduler.capture_snapshots((PathGlobsAndRoot(globs, text_type(temp_dir)),))[0]
      self.assert_snapshot_equals(snapshot, ["roland"], DirectoryDigest(
        text_type("63949aa823baf765eff07b946050d76ec0033144c785a94d3ebd82baa931cd16"),
        80
      ))
