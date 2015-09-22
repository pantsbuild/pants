# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import atexit
import os
import tempfile
import unittest

import mox
import six

from pants.util import dirutil
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import (_mkdtemp_unregister_cleaner, fast_relpath, get_basedir,
                                relative_symlink, relativize_paths, safe_mkdir)


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
    if six.PY2:
      with temporary_dir() as tmpdir:
        safe_mkdir(os.path.join(tmpdir, '中文'))
        if isinstance(tmpdir, unicode):  # noqa
          tmpdir = tmpdir.encode('utf-8')
        for _, dirs, _ in dirutil.safe_walk(tmpdir):
          self.assertTrue(all(isinstance(dirname, unicode) for dirname in dirs))  # noqa

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
