# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import atexit
import os
import tempfile

import mox
import unittest

from pants.util import dirutil
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import _mkdtemp_unregister_cleaner, safe_mkdir


class DirutilTest(unittest.TestCase):

  def setUp(self):
    self._mox = mox.Mox()
    # Ensure we start in a clean state.
    _mkdtemp_unregister_cleaner()

  def tearDown(self):
    self._mox.UnsetStubs()

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
      self.assertEquals(set([DIR1, DIR2]), dirutil._MKDTEMP_DIRS['unicorn'])
      dirutil._mkdtemp_atexit_cleaner()
      self.assertNotIn('unicorn', dirutil._MKDTEMP_DIRS)
      self.assertEquals(set(['yoyo']), dirutil._MKDTEMP_DIRS['fluffypants'])
    finally:
      dirutil._MKDTEMP_DIRS.pop('unicorn', None)
      dirutil._MKDTEMP_DIRS.pop('fluffypants', None)
      dirutil._mkdtemp_unregister_cleaner()

    self._mox.VerifyAll()

  def test_safe_walk(self):
    with temporary_dir() as tmpdir:
      safe_mkdir(os.path.join(tmpdir, '中文'))
      if isinstance(tmpdir, unicode):
        tmpdir = tmpdir.encode('utf-8')
      for _, dirs, _ in dirutil.safe_walk(tmpdir):
        self.assertTrue(all(isinstance(dirname, unicode) for dirname in dirs))
