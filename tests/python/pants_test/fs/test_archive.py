# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import unittest

from pants.fs.archive import TAR, TBZ2, TGZ, ZIP
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir, touch


class ArchiveTest(unittest.TestCase):
  def round_trip(self, archiver, empty_dirs):
    def listtree(root):
      listing = set()
      for path, dirs, files in os.walk(root):
        relpath = os.path.normpath(os.path.relpath(path, root)).decode('utf-8')
        if empty_dirs:
          listing.update(os.path.normpath(os.path.join(relpath, d.decode('utf-8'))) for d in dirs)
        listing.update(os.path.normpath(os.path.join(relpath, f.decode('utf-8'))) for f in files)
      return listing

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
            fromlisting = listtree(fromdir)
            if prefix:
              fromlisting = set(os.path.join(prefix, x) for x in fromlisting)
              if empty_dirs:
                fromlisting.add(prefix)
            self.assertEqual(fromlisting, listtree(todir))

    test_round_trip()
    test_round_trip(prefix='jake')

  def test_tar(self):
    self.round_trip(TAR, empty_dirs=True)
    self.round_trip(TGZ, empty_dirs=True)
    self.round_trip(TBZ2, empty_dirs=True)

  def test_zip(self):
    self.round_trip(ZIP, empty_dirs=False)
