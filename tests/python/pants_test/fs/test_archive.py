# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import unittest2 as unittest

from pants.fs.archive import TAR, TBZ2, TGZ, ZIP
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir, safe_walk, touch


class ArchiveTest(unittest.TestCase):
  def _listtree(self, root, empty_dirs):
    listing = set()
    for path, dirs, files in safe_walk(root):
      relpath = os.path.normpath(os.path.relpath(path, root))
      if empty_dirs:
        listing.update(os.path.normpath(os.path.join(relpath, d)) for d in dirs)
      listing.update(os.path.normpath(os.path.join(relpath, f)) for f in files)
    return listing

  def round_trip(self, archiver, empty_dirs):
    def test_round_trip(prefix=None):
      with temporary_dir() as fromdir:
        safe_mkdir(os.path.join(fromdir, 'a/b/c'))
        touch(os.path.join(fromdir, 'a/b/d/e.txt'))
        touch(os.path.join(fromdir, 'a/b/d/文件.java'))
        touch(os.path.join(fromdir, 'a/b/文件/f.java'))

        with temporary_dir() as archivedir:
          archive = archiver.create(fromdir, archivedir, 'archive', prefix=prefix)
          with temporary_dir() as todir:
            archiver.extract(archive, todir)
            fromlisting = self._listtree(fromdir, empty_dirs)
            if prefix:
              fromlisting = set(os.path.join(prefix, x) for x in fromlisting)
              if empty_dirs:
                fromlisting.add(prefix)
            self.assertEqual(fromlisting, self._listtree(todir, empty_dirs))

    test_round_trip()
    test_round_trip(prefix='jake')

  def test_tar(self):
    self.round_trip(TAR, empty_dirs=True)
    self.round_trip(TGZ, empty_dirs=True)
    self.round_trip(TBZ2, empty_dirs=True)

  def test_zip(self):
    self.round_trip(ZIP, empty_dirs=False)

  def test_zip_filter(self):
    def do_filter(path):
      return path == 'allowed.txt'

    with temporary_dir() as fromdir:
      touch(os.path.join(fromdir, 'allowed.txt'))
      touch(os.path.join(fromdir, 'disallowed.txt'))

      with temporary_dir() as archivedir:
        archive = ZIP.create(fromdir, archivedir, 'archive')
        with temporary_dir() as todir:
          ZIP.extract(archive, todir, filter=do_filter)
          self.assertEquals(set(['allowed.txt']), self._listtree(todir, empty_dirs=False))
