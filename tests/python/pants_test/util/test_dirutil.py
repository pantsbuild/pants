# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import atexit
import errno
import os
import tempfile
import time
import unittest

import mock
import mox
import six

from pants.util import dirutil
from pants.util.contextutil import pushd, temporary_dir
from pants.util.dirutil import (_mkdtemp_unregister_cleaner, absolute_symlink, fast_relpath,
                                get_basedir, read_file, relative_symlink, relativize_paths, rm_rf,
                                safe_concurrent_creation, safe_file_dump, safe_mkdir,
                                safe_rm_oldest_items_in_dir, touch)


class DirutilTest(unittest.TestCase):

  def setUp(self):
    self._mox = mox.Mox()
    # Ensure we start in a clean state.
    _mkdtemp_unregister_cleaner()

  def tearDown(self):
    self._mox.UnsetStubs()

  def test_fast_relpath(self):
    def assertRelpath(expected, path, start):
      self.assertEquals(expected, fast_relpath(path, start))
    assertRelpath('c', '/a/b/c', '/a/b')
    assertRelpath('c', '/a/b/c', '/a/b/')
    assertRelpath('c', 'b/c', 'b')
    assertRelpath('c', 'b/c', 'b/')
    assertRelpath('c/', 'b/c/', 'b')
    assertRelpath('c/', 'b/c/', 'b/')
    assertRelpath('', 'c/', 'c/')
    assertRelpath('', 'c', 'c')
    assertRelpath('c/', 'c/', '')
    assertRelpath('c', 'c', '')

  def test_fast_relpath_invalid(self):
    with self.assertRaises(ValueError):
      fast_relpath('/a/b', '/a/baseball')
    with self.assertRaises(ValueError):
      fast_relpath('/a/baseball', '/a/b')

  def test_mkdtemp_setup_teardown(self):
    def faux_cleaner():
      pass

    DIR1, DIR2 = 'fake_dir1__does_not_exist', 'fake_dir2__does_not_exist'
    self._mox.StubOutWithMock(atexit, 'register')
    self._mox.StubOutWithMock(os, 'getpid')
    self._mox.StubOutWithMock(tempfile, 'mkdtemp')
    self._mox.StubOutWithMock(dirutil, 'safe_rmtree')
    atexit.register(faux_cleaner)  # Ensure only called once.
    tempfile.mkdtemp(dir='1').AndReturn(DIR1)
    tempfile.mkdtemp(dir='2').AndReturn(DIR2)
    os.getpid().MultipleTimes().AndReturn('unicorn')
    dirutil.safe_rmtree(DIR1)
    dirutil.safe_rmtree(DIR2)
    # Make sure other "pids" are not cleaned.
    dirutil._MKDTEMP_DIRS['fluffypants'].add('yoyo')

    try:
      self._mox.ReplayAll()
      self.assertEquals(DIR1, dirutil.safe_mkdtemp(dir='1', cleaner=faux_cleaner))
      self.assertEquals(DIR2, dirutil.safe_mkdtemp(dir='2', cleaner=faux_cleaner))
      self.assertIn('unicorn', dirutil._MKDTEMP_DIRS)
      self.assertEquals({DIR1, DIR2}, dirutil._MKDTEMP_DIRS['unicorn'])
      dirutil._mkdtemp_atexit_cleaner()
      self.assertNotIn('unicorn', dirutil._MKDTEMP_DIRS)
      self.assertEquals({'yoyo'}, dirutil._MKDTEMP_DIRS['fluffypants'])
    finally:
      dirutil._MKDTEMP_DIRS.pop('unicorn', None)
      dirutil._MKDTEMP_DIRS.pop('fluffypants', None)
      dirutil._mkdtemp_unregister_cleaner()

    self._mox.VerifyAll()

  def test_safe_walk(self):
    """Test that directory names are correctly represented as unicode strings"""
    # This test is unnecessary in python 3 since all strings are unicode there is no
    # unicode constructor.
    with temporary_dir() as tmpdir:
      safe_mkdir(os.path.join(tmpdir, '中文'))
      if isinstance(tmpdir, six.text_type):
        tmpdir = tmpdir.encode('utf-8')
      for _, dirs, _ in dirutil.safe_walk(tmpdir):
        self.assertTrue(all(isinstance(dirname, six.text_type) for dirname in dirs))

  def test_relativize_paths(self):
    build_root = '/build-root'
    jar_outside_build_root = os.path.join('/outside-build-root', 'bar.jar')
    classpath = [os.path.join(build_root, 'foo.jar'), jar_outside_build_root]
    relativized_classpath = relativize_paths(classpath, build_root)
    jar_relpath = os.path.relpath(jar_outside_build_root, build_root)
    self.assertEquals(['foo.jar', jar_relpath], relativized_classpath)

  def test_relative_symlink(self):
    with temporary_dir() as tmpdir_1:  # source and link in same dir
      source = os.path.join(tmpdir_1, 'source')
      link = os.path.join(tmpdir_1, 'link')
      rel_path = os.path.relpath(source, os.path.dirname(link))
      relative_symlink(source, link)
      self.assertTrue(os.path.islink(link))
      self.assertEquals(rel_path, os.readlink(link))

  def test_relative_symlink_source_parent(self):
    with temporary_dir() as tmpdir_1:  # source in parent dir of link
      child = os.path.join(tmpdir_1, 'child')
      os.mkdir(child)
      source = os.path.join(tmpdir_1, 'source')
      link = os.path.join(child, 'link')
      relative_symlink(source, link)
      rel_path = os.path.relpath(source, os.path.dirname(link))
      self.assertTrue(os.path.islink(link))
      self.assertEquals(rel_path, os.readlink(link))

  def test_relative_symlink_link_parent(self):
    with temporary_dir() as tmpdir_1:  # link in parent dir of source
      child = os.path.join(tmpdir_1, 'child')
      source = os.path.join(child, 'source')
      link = os.path.join(tmpdir_1, 'link')
      relative_symlink(source, link)
      rel_path = os.path.relpath(source, os.path.dirname(link))
      self.assertTrue(os.path.islink(link))
      self.assertEquals(rel_path, os.readlink(link))

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

  def test_get_basedir(self):
    self.assertEquals(get_basedir('foo/bar/baz'), 'foo')
    self.assertEquals(get_basedir('/foo/bar/baz'), '')
    self.assertEquals(get_basedir('foo'), 'foo')

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

  def test_readwrite_file(self):
    with temporary_dir() as td:
      test_filename = os.path.join(td, 'test.out')
      test_content = '3333'
      safe_file_dump(test_filename, test_content)
      self.assertEqual(read_file(test_filename), test_content)

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

  def test_safe_concurrent_creation_exception_still_renames(self):
    with temporary_dir() as td:
      expected_file = os.path.join(td, 'expected_file')

      with self.assertRaises(ZeroDivisionError):
        with safe_concurrent_creation(expected_file) as safe_path:
          os.mkdir(safe_path)
          self.assertTrue(os.path.exists(safe_path))
          raise ZeroDivisionError('zomg')

      self.assertFalse(os.path.exists(safe_path))
      self.assertTrue(os.path.exists(expected_file))

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

  def test_absolute_symlink(self):
    def _create_and_check_link(source, link):
      absolute_symlink(source, link)
      self.assertTrue(os.path.islink(link))
      self.assertEquals(source, os.readlink(link))

    with temporary_dir() as td:
      link = os.path.join(td, 'link')

      # Do it twice, to make sure we can overwrite existing link
      source = os.path.join(td, 'source1')
      _create_and_check_link(source, link)
      source = os.path.join(td, 'source2')
      _create_and_check_link(source, link)

      # Check if parent dirs will be created for the link
      link = os.path.join(td, 'a/b/c/link')
      _create_and_check_link(source, link)
