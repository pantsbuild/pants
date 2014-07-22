# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import atexit
import os
import tempfile

import mox
import pytest

from pants.util import dirutil


def test_mkdtemp_setup_teardown():
  m = mox.Mox()

  def faux_cleaner():
    pass

  DIR1, DIR2 = 'fake_dir1__does_not_exist', 'fake_dir2__does_not_exist'
  m.StubOutWithMock(atexit, 'register')
  m.StubOutWithMock(os, 'getpid')
  m.StubOutWithMock(tempfile, 'mkdtemp')
  m.StubOutWithMock(dirutil, 'safe_rmtree')
  atexit.register(faux_cleaner) # ensure only called once
  tempfile.mkdtemp(dir='1').AndReturn(DIR1)
  tempfile.mkdtemp(dir='2').AndReturn(DIR2)
  os.getpid().MultipleTimes().AndReturn('unicorn')
  dirutil.safe_rmtree(DIR1)
  dirutil.safe_rmtree(DIR2)
  # make sure other "pids" are not cleaned
  dirutil._MKDTEMP_DIRS['fluffypants'].add('yoyo')

  try:
    m.ReplayAll()
    assert dirutil.safe_mkdtemp(dir='1', cleaner=faux_cleaner) == DIR1
    assert dirutil.safe_mkdtemp(dir='2', cleaner=faux_cleaner) == DIR2
    assert 'unicorn' in dirutil._MKDTEMP_DIRS
    assert dirutil._MKDTEMP_DIRS['unicorn'] == set([DIR1, DIR2])
    dirutil._mkdtemp_atexit_cleaner()
    assert 'unicorn' not in dirutil._MKDTEMP_DIRS
    assert dirutil._MKDTEMP_DIRS['fluffypants'] == set(['yoyo'])

  finally:
    dirutil._MKDTEMP_DIRS.pop('unicorn', None)
    dirutil._MKDTEMP_DIRS.pop('fluffypants', None)
    dirutil._mkdtemp_unregister_cleaner()

    m.UnsetStubs()
    m.VerifyAll()
