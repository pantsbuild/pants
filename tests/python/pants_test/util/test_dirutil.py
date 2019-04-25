# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import errno
import os
import time
import unittest
from builtins import open, str
from contextlib import contextmanager

import mock

from pants.util import dirutil
from pants.util.contextutil import pushd, temporary_dir
from pants.util.dirutil import (ExistingDirError, ExistingFileError, _mkdtemp_unregister_cleaner,
                                absolute_symlink, check_no_overlapping_paths, fast_relpath,
                                get_basedir, longest_dir_prefix, mergetree, read_file,
                                relative_symlink, relativize_paths, rm_rf, safe_concurrent_creation,
                                safe_file_dump, safe_mkdir, safe_mkdtemp, safe_open,
                                safe_rm_oldest_items_in_dir, safe_rmtree, touch)
from pants.util.objects import datatype


def strict_patch(target, **kwargs):
  return mock.patch(target, autospec=True, spec_set=True, **kwargs)


class DirutilTest(unittest.TestCase):

  def setUp(self):
    # Ensure we start in a clean state.
    _mkdtemp_unregister_cleaner()

  def test_longest_dir_prefix(self):
    # Find the longest prefix (standard case).
    prefixes = ['hello', 'hello_world', 'hello/world', 'helloworld']
    self.assertEqual(longest_dir_prefix('hello/world/pants', prefixes),
                      'hello/world')
    self.assertEqual(longest_dir_prefix('hello/', prefixes),
                      'hello')
    self.assertEqual(longest_dir_prefix('hello', prefixes),
                      'hello')
    self.assertEqual(longest_dir_prefix('scoobydoobydoo', prefixes),
                      None)

  def test_longest_dir_prefix_special(self):
    # Ensure that something that is a longest prefix, but not a longest dir
    # prefix, is not tagged.
    prefixes = ['helloworldhowareyou', 'helloworld']
    self.assertEqual(longest_dir_prefix('helloworldhowareyoufine/', prefixes),
                      None)
    self.assertEqual(longest_dir_prefix('helloworldhowareyoufine', prefixes),
                      None)

  def test_fast_relpath(self):
    def assertRelpath(expected, path, start):
      self.assertEqual(expected, fast_relpath(path, start))
    assertRelpath('c', '/a/b/c', '/a/b')
    assertRelpath('c', '/a/b/c', '/a/b/')
    assertRelpath('c', 'b/c', 'b')
    assertRelpath('c', 'b/c', 'b/')
    assertRelpath('c/', 'b/c/', 'b')
    assertRelpath('c/', 'b/c/', 'b/')
    assertRelpath('', 'c/', 'c/')
    assertRelpath('', 'c', 'c')
    assertRelpath('', 'c/', 'c')
    assertRelpath('', 'c', 'c/')
    assertRelpath('c/', 'c/', '')
    assertRelpath('c', 'c', '')

  def test_fast_relpath_invalid(self):
    with self.assertRaises(ValueError):
      fast_relpath('/a/b', '/a/baseball')
    with self.assertRaises(ValueError):
      fast_relpath('/a/baseball', '/a/b')

  @strict_patch('atexit.register')
  @strict_patch('os.getpid')
  @strict_patch('pants.util.dirutil.safe_rmtree')
  @strict_patch('tempfile.mkdtemp')
  def test_mkdtemp_setup_teardown(self,
                                  tempfile_mkdtemp,
                                  dirutil_safe_rmtree,
                                  os_getpid,
                                  atexit_register):
    def faux_cleaner():
      pass

    DIR1, DIR2 = 'fake_dir1__does_not_exist', 'fake_dir2__does_not_exist'

    # Make sure other "pids" are not cleaned.
    dirutil._MKDTEMP_DIRS['fluffypants'].add('yoyo')

    tempfile_mkdtemp.side_effect = (DIR1, DIR2)
    os_getpid.return_value = 'unicorn'
    try:
      self.assertEqual(DIR1, dirutil.safe_mkdtemp(dir='1', cleaner=faux_cleaner))
      self.assertEqual(DIR2, dirutil.safe_mkdtemp(dir='2', cleaner=faux_cleaner))
      self.assertIn('unicorn', dirutil._MKDTEMP_DIRS)
      self.assertEqual({DIR1, DIR2}, dirutil._MKDTEMP_DIRS['unicorn'])
      dirutil._mkdtemp_atexit_cleaner()
      self.assertNotIn('unicorn', dirutil._MKDTEMP_DIRS)
      self.assertEqual({'yoyo'}, dirutil._MKDTEMP_DIRS['fluffypants'])
    finally:
      dirutil._MKDTEMP_DIRS.pop('unicorn', None)
      dirutil._MKDTEMP_DIRS.pop('fluffypants', None)
      dirutil._mkdtemp_unregister_cleaner()

    atexit_register.assert_called_once_with(faux_cleaner)
    self.assertTrue(os_getpid.called)
    self.assertEqual([mock.call(dir='1'), mock.call(dir='2')], tempfile_mkdtemp.mock_calls)
    self.assertEqual(sorted([mock.call(DIR1), mock.call(DIR2)]), sorted(dirutil_safe_rmtree.mock_calls))

  def test_safe_walk(self):
    """Test that directory names are correctly represented as unicode strings"""
    # This test is unnecessary in python 3 since all strings are unicode there is no
    # unicode constructor.
    with temporary_dir() as tmpdir:
      safe_mkdir(os.path.join(tmpdir, '中文'))
      if isinstance(tmpdir, str):
        tmpdir = tmpdir.encode('utf-8')
      for _, dirs, _ in dirutil.safe_walk(tmpdir):
        self.assertTrue(all(isinstance(dirname, str) for dirname in dirs))

  @contextmanager
  def tree(self):
    # root/
    #   a/
    #     b/
    #       1
    #       2
    #     2 -> root/a/b/2
    #   b -> root/a/b
    with temporary_dir() as root:
      with safe_open(os.path.join(root, 'a', 'b', '1'), 'wb') as fp:
        fp.write(b'1')
      touch(os.path.join(root, 'a', 'b', '2'))
      os.symlink(os.path.join(root, 'a', 'b', '2'), os.path.join(root, 'a', '2'))
      os.symlink(os.path.join(root, 'a', 'b'), os.path.join(root, 'b'))
      with temporary_dir() as dst:
        yield root, dst

  class Dir(datatype(['path'])):
    pass

  class File(datatype(['path', 'contents'])):
    @classmethod
    def empty(cls, path):
      return cls(path, contents='')

    @classmethod
    def read(cls, root, relpath):
      with open(os.path.join(root, relpath), 'r') as fp:
        return cls(relpath, fp.read())

  class Symlink(datatype(['path'])):
    pass

  def assert_tree(self, root, *expected):
    def collect_tree():
      for path, dirnames, filenames in os.walk(root, followlinks=False):
        relpath = os.path.relpath(path, root)
        if relpath == os.curdir:
          relpath = ''
        for dirname in dirnames:
          dirpath = os.path.join(relpath, dirname)
          if os.path.islink(os.path.join(path, dirname)):
            yield self.Symlink(dirpath)
          else:
            yield self.Dir(dirpath)
        for filename in filenames:
          filepath = os.path.join(relpath, filename)
          if os.path.islink(os.path.join(path, filename)):
            yield self.Symlink(filepath)
          else:
            yield self.File.read(root, filepath)

    self.assertEqual(frozenset(expected), frozenset(collect_tree()))

  def test_mergetree_existing(self):
    with self.tree() as (src, dst):
      # Existing empty files
      touch(os.path.join(dst, 'c', '1'))
      touch(os.path.join(dst, 'a', 'b', '1'))

      mergetree(src, dst)

      self.assert_tree(dst,
                       self.Dir('a'),
                       self.File.empty('a/2'),
                       self.Dir('a/b'),

                       # Existing overlapping file should be overlayed.
                       self.File('a/b/1', contents='1'),

                       self.File.empty('a/b/2'),
                       self.Dir('b'),
                       self.File('b/1', contents='1'),
                       self.File.empty('b/2'),
                       self.Dir('c'),

                       # Existing non-overlapping file should be preserved.
                       self.File.empty('c/1'))

  def test_mergetree_existing_file_mismatch(self):
    with self.tree() as (src, dst):
      touch(os.path.join(dst, 'a'))
      with self.assertRaises(ExistingFileError):
        mergetree(src, dst)

  def test_mergetree_existing_dir_mismatch(self):
    with self.tree() as (src, dst):
      os.makedirs(os.path.join(dst, 'b', '1'))
      with self.assertRaises(ExistingDirError):
        mergetree(src, dst)

  def test_mergetree_new(self):
    with self.tree() as (src, dst_root):
      dst = os.path.join(dst_root, 'dst')

      mergetree(src, dst)

      self.assert_tree(dst,
                       self.Dir('a'),
                       self.File.empty('a/2'),
                       self.Dir('a/b'),
                       self.File('a/b/1', contents='1'),
                       self.File.empty('a/b/2'),
                       self.Dir('b'),
                       self.File('b/1', contents='1'),
                       self.File.empty('b/2'))

  def test_mergetree_ignore_files(self):
    with self.tree() as (src, dst):
      def ignore(root, names):
        if root == os.path.join(src, 'a', 'b'):
          return ['1', '2']

      mergetree(src, dst, ignore=ignore)

      self.assert_tree(dst,
                       self.Dir('a'),
                       self.File.empty('a/2'),
                       self.Dir('a/b'),
                       self.Dir('b'),
                       self.File('b/1', contents='1'),
                       self.File.empty('b/2'))

  def test_mergetree_ignore_dirs(self):
    with self.tree() as (src, dst):
      def ignore(root, names):
        if root == os.path.join(src, 'a'):
          return ['b']

      mergetree(src, dst, ignore=ignore)

      self.assert_tree(dst,
                       self.Dir('a'),
                       self.File.empty('a/2'),
                       self.Dir('b'),
                       self.File('b/1', contents='1'),
                       self.File.empty('b/2'))

  def test_mergetree_symlink(self):
    with self.tree() as (src, dst):
      mergetree(src, dst, symlinks=True)

      self.assert_tree(dst,
                       self.Dir('a'),
                       self.Symlink('a/2'),
                       self.Dir('a/b'),
                       self.File('a/b/1', contents='1'),
                       self.File.empty('a/b/2'),

                       # NB: assert_tree does not follow symlinks and so does not descend into the
                       # symlinked b/ dir to find b/1 and b/2
                       self.Symlink('b'))

  def test_relativize_paths(self):
    build_root = '/build-root'
    jar_outside_build_root = os.path.join('/outside-build-root', 'bar.jar')
    classpath = [os.path.join(build_root, 'foo.jar'), jar_outside_build_root]
    relativized_classpath = relativize_paths(classpath, build_root)
    jar_relpath = os.path.relpath(jar_outside_build_root, build_root)
    self.assertEqual(['foo.jar', jar_relpath], relativized_classpath)

  def test_relative_symlink(self):
    with temporary_dir() as tmpdir_1:  # source and link in same dir
      source = os.path.join(tmpdir_1, 'source')
      link = os.path.join(tmpdir_1, 'link')
      rel_path = os.path.relpath(source, os.path.dirname(link))
      relative_symlink(source, link)
      self.assertTrue(os.path.islink(link))
      self.assertEqual(rel_path, os.readlink(link))

  def test_relative_symlink_source_parent(self):
    with temporary_dir() as tmpdir_1:  # source in parent dir of link
      child = os.path.join(tmpdir_1, 'child')
      os.mkdir(child)
      source = os.path.join(tmpdir_1, 'source')
      link = os.path.join(child, 'link')
      relative_symlink(source, link)
      rel_path = os.path.relpath(source, os.path.dirname(link))
      self.assertTrue(os.path.islink(link))
      self.assertEqual(rel_path, os.readlink(link))

  def test_relative_symlink_link_parent(self):
    with temporary_dir() as tmpdir_1:  # link in parent dir of source
      child = os.path.join(tmpdir_1, 'child')
      source = os.path.join(child, 'source')
      link = os.path.join(tmpdir_1, 'link')
      relative_symlink(source, link)
      rel_path = os.path.relpath(source, os.path.dirname(link))
      self.assertTrue(os.path.islink(link))
      self.assertEqual(rel_path, os.readlink(link))

  def test_relative_symlink_same_paths(self):
    with temporary_dir() as tmpdir_1:  # source is link
      source = os.path.join(tmpdir_1, 'source')
      with self.assertRaisesRegexp(ValueError, r'Path for link is identical to source'):
        relative_symlink(source, source)

  def test_relative_symlink_bad_source(self):
    with temporary_dir() as tmpdir_1:  # source is not absolute
      source = os.path.join('foo', 'bar')
      link = os.path.join(tmpdir_1, 'link')
      with self.assertRaisesRegexp(ValueError, r'Path for source.*absolute'):
        relative_symlink(source, link)

  def test_relative_symlink_bad_link(self):
    with temporary_dir() as tmpdir_1:  # link is not absolute
      source = os.path.join(tmpdir_1, 'source')
      link = os.path.join('foo', 'bar')
      with self.assertRaisesRegexp(ValueError, r'Path for link.*absolute'):
        relative_symlink(source, link)

  def test_relative_symlink_overwrite_existing_file(self):
    # Succeeds, since os.unlink can be safely called on files that aren't symlinks.
    with temporary_dir() as tmpdir_1:  # source and link in same dir
      source = os.path.join(tmpdir_1, 'source')
      link_path = os.path.join(tmpdir_1, 'link')
      touch(link_path)
      relative_symlink(source, link_path)

  def test_relative_symlink_exception_on_existing_dir(self):
    # This historically was an uncaught exception, the tested behavior is to begin catching the error.
    with temporary_dir() as tmpdir_1:
      source = os.path.join(tmpdir_1, 'source')
      link_path = os.path.join(tmpdir_1, 'link')

      safe_mkdir(link_path)
      with self.assertRaisesRegexp(ValueError, r'Path for link.*overwrite an existing directory*'):
        relative_symlink(source, link_path)

  def test_get_basedir(self):
    self.assertEqual(get_basedir('foo/bar/baz'), 'foo')
    self.assertEqual(get_basedir('/foo/bar/baz'), '')
    self.assertEqual(get_basedir('foo'), 'foo')

  def test_rm_rf_file(self, file_name='./foo'):
    with temporary_dir() as td, pushd(td):
      touch(file_name)
      self.assertTrue(os.path.isfile(file_name))
      rm_rf(file_name)
      self.assertFalse(os.path.exists(file_name))

  def test_rm_rf_dir(self, dir_name='./bar'):
    with temporary_dir() as td, pushd(td):
      safe_mkdir(dir_name)
      self.assertTrue(os.path.isdir(dir_name))
      rm_rf(dir_name)
      self.assertFalse(os.path.exists(dir_name))

  def test_rm_rf_nonexistent(self, file_name='./non_existent_file'):
    with temporary_dir() as td, pushd(td):
      rm_rf(file_name)

  def test_rm_rf_permission_error_raises(self, file_name='./perm_guarded_file'):
    with temporary_dir() as td, pushd(td), \
         mock.patch('pants.util.dirutil.shutil.rmtree') as mock_rmtree, \
         self.assertRaises(OSError):
      mock_rmtree.side_effect = OSError(errno.EACCES, os.strerror(errno.EACCES))
      touch(file_name)
      rm_rf(file_name)

  def test_rm_rf_no_such_file_not_an_error(self, file_name='./vanishing_file'):
    with temporary_dir() as td, pushd(td), \
         mock.patch('pants.util.dirutil.shutil.rmtree') as mock_rmtree:
      mock_rmtree.side_effect = OSError(errno.ENOENT, os.strerror(errno.ENOENT))
      touch(file_name)
      rm_rf(file_name)

  def assert_dump_and_read(self, test_content, dump_kwargs, read_kwargs):
    with temporary_dir() as td:
      test_filename = os.path.join(td, 'test.out')
      safe_file_dump(test_filename, test_content, **dump_kwargs)
      self.assertEqual(read_file(test_filename, **read_kwargs), test_content)

  def test_readwrite_file_binary(self):
    self.assert_dump_and_read(b'333', {'mode': 'wb'}, {'binary_mode': True})
    with self.assertRaises(Exception):
      # File is not opened as binary.
      self.assert_dump_and_read(b'333', {'mode': 'w'}, {'binary_mode': True})

  def test_readwrite_file_unicode(self):
    self.assert_dump_and_read('✓', {'mode': 'w'}, {'binary_mode': False})
    with self.assertRaises(Exception):
      # File is opened as binary.
      self.assert_dump_and_read('✓', {'mode': 'wb'}, {'binary_mode': True})

  def test_safe_concurrent_creation(self):
    with temporary_dir() as td:
      expected_file = os.path.join(td, 'expected_file')
      with safe_concurrent_creation(expected_file) as tmp_expected_file:
        os.mkdir(tmp_expected_file)
        self.assertTrue(os.path.exists(tmp_expected_file))
        self.assertFalse(os.path.exists(expected_file))
      self.assertTrue(os.path.exists(expected_file))

  def test_safe_concurrent_creation_noop(self):
    with temporary_dir() as td:
      expected_file = os.path.join(td, 'parent_dir', 'expected_file')

      # Ensure safe_concurrent_creation() doesn't bomb if we don't write the expected files.
      with safe_concurrent_creation(expected_file):
        pass

      self.assertFalse(os.path.exists(expected_file))
      self.assertTrue(os.path.exists(os.path.dirname(expected_file)))

  def test_safe_concurrent_creation_exception_handling(self):
    with temporary_dir() as td:
      expected_file = os.path.join(td, 'expected_file')

      with self.assertRaises(ZeroDivisionError):
        with safe_concurrent_creation(expected_file) as safe_path:
          os.mkdir(safe_path)
          self.assertTrue(os.path.exists(safe_path))
          raise ZeroDivisionError('zomg')

      self.assertFalse(os.path.exists(safe_path))
      self.assertFalse(os.path.exists(expected_file))

  def test_safe_rm_oldest_items_in_dir(self):
    with temporary_dir() as td:
      touch(os.path.join(td, 'file1'))
      safe_mkdir(os.path.join(td, 'file2'))
      # Time modified is only accurate to second.
      time.sleep(1.1)
      touch(os.path.join(td, 'file3'))
      touch(os.path.join(td, 'file4'))
      safe_mkdir(os.path.join(td, 'file5'))

      safe_rm_oldest_items_in_dir(td, 3)

      self.assertFalse(os.path.exists(os.path.join(td, 'file1')))
      self.assertFalse(os.path.exists(os.path.join(td, 'file2')))

      self.assertTrue(os.path.exists(os.path.join(td, 'file3')))
      self.assertTrue(os.path.exists(os.path.join(td, 'file4')))
      self.assertTrue(os.path.exists(os.path.join(td, 'file5')))

  def test_safe_rm_oldest_items_in_dir_with_excludes(self):
    with temporary_dir() as td:
      touch(os.path.join(td, 'file1'))
      touch(os.path.join(td, 'file2'))
      touch(os.path.join(td, 'file3'))
      # Time modified is only accurate to second.
      time.sleep(1.1)
      touch(os.path.join(td, 'file4'))

      excludes = [os.path.join(td, 'file1'),
                  os.path.join(td, 'file2')]
      safe_rm_oldest_items_in_dir(td, 1, excludes)

      self.assertTrue(os.path.exists(os.path.join(td, 'file1')))
      self.assertTrue(os.path.exists(os.path.join(td, 'file2')))
      self.assertTrue(os.path.exists(os.path.join(td, 'file4')))

      self.assertFalse(os.path.exists(os.path.join(td, 'file3')))

  def test_safe_rm_oldest_items_in_dir_noop(self):
    with temporary_dir() as td:
      safe_rm_oldest_items_in_dir(td, 1)
      touch(os.path.join(td, 'file1'))
      self.assertEqual(len(os.listdir(td)), 1)

  def test_safe_rmtree_link(self):
    with temporary_dir() as td:
      real = os.path.join(td, 'real')
      link = os.path.join(td, 'link')
      os.mkdir(real)
      os.symlink(real, link)
      self.assertTrue(os.path.exists(real))
      self.assertTrue(os.path.exists(link))
      safe_rmtree(link)
      self.assertTrue(os.path.exists(real))
      self.assertFalse(os.path.exists(link))


class AbsoluteSymlinkTest(unittest.TestCase):
  def setUp(self):
    self.td = safe_mkdtemp()
    self.addCleanup(safe_rmtree, self.td)

    self.source = os.path.join(self.td, 'source')
    self.link = os.path.join(self.td, 'link')

  def _create_and_check_link(self, source, link):
    absolute_symlink(source, link)
    self.assertTrue(os.path.islink(link))
    self.assertEqual(source, os.readlink(link))

  def test_link(self):
    # Check if parent dirs will be created for the link
    link = os.path.join(self.td, 'a', 'b', 'c', 'self.link')
    self._create_and_check_link(self.source, link)

  def test_overwrite_link_link(self):
    # Do it twice, to make sure we can overwrite existing link
    self._create_and_check_link(self.source, self.link)
    self._create_and_check_link(self.source, self.link)

  def test_overwrite_link_file(self):
    with open(self.source, 'w') as fp:
      fp.write('evidence')

    # Do it twice, to make sure we can overwrite existing link
    self._create_and_check_link(self.source, self.link)
    self._create_and_check_link(self.source, self.link)

    # The link should have been deleted (over-written), not the file it pointed to.
    with open(self.source, 'r') as fp:
      self.assertEqual('evidence', fp.read())

  def test_overwrite_link_dir(self):
    nested_dir = os.path.join(self.source, 'a', 'b', 'c')
    os.makedirs(nested_dir)

    # Do it twice, to make sure we can overwrite existing link
    self._create_and_check_link(self.source, self.link)
    self._create_and_check_link(self.source, self.link)

    # The link should have been deleted (over-written), not the dir it pointed to.
    self.assertTrue(os.path.isdir(nested_dir))

  def test_overwrite_file(self):
    touch(self.link)
    self._create_and_check_link(self.source, self.link)

  def test_overwrite_dir(self):
    os.makedirs(os.path.join(self.link, 'a', 'b', 'c'))
    self._create_and_check_link(self.source, self.link)

  def test_check_no_overlapping_paths_two_same(self):
    paths = ["/path/to/file", "/path/to/file", "/no/path/to/file"]
    with self.assertRaises(ValueError):
      check_no_overlapping_paths(paths)

  def test_check_no_overlapping_paths_prefix(self):
    paths = ["/path/to", "/path/to/file", "/no/path/to/file"]
    with self.assertRaises(ValueError):
      check_no_overlapping_paths(paths)

  def test_check_no_overlapping_paths_unique_paths(self):
    paths = ["/he/went/to/the/store", "/she/saw/a/movie", "/no/one/knew/where/to/go"]
    # This test is successful if nothing happens when calling check_no_overlapping_paths(paths)
    check_no_overlapping_paths(paths)
