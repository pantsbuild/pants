# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from pants.fs.archive import archiver
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import relative_symlink, safe_mkdir, safe_walk, touch


class ArchiveTest(unittest.TestCase):
  def _listtree(self, root, empty_dirs):
    listing = set()
    for path, dirs, files in safe_walk(root):
      relpath = os.path.normpath(os.path.relpath(path, root))
      if empty_dirs:
        listing.update(os.path.normpath(os.path.join(relpath, d)) for d in dirs)
      listing.update(os.path.normpath(os.path.join(relpath, f)) for f in files)
    return listing

  def round_trip(self, archiver, expected_ext, empty_dirs):
    def test_round_trip(prefix=None):
      with temporary_dir() as fromdir:
        safe_mkdir(os.path.join(fromdir, 'a/b/c'))
        touch(os.path.join(fromdir, 'a/b/d/e.txt'))
        touch(os.path.join(fromdir, 'a/b/d/文件.java'))
        touch(os.path.join(fromdir, 'a/b/文件/f.java'))

        with temporary_dir() as archivedir:
          archive = archiver.create(fromdir, archivedir, 'archive', prefix=prefix)

          # can't use os.path.splitext because 'abc.tar.gz' would return '.gz'.
          self.assertTrue(archive.endswith(expected_ext),
              'archive filename {0} does not end with expected extension {1}'.format(
                  archive, expected_ext))

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
    self.round_trip(archiver('tar'), expected_ext='tar', empty_dirs=True)
    self.round_trip(archiver('tgz'), expected_ext='tar.gz', empty_dirs=True)
    self.round_trip(archiver('tbz2'), expected_ext='tar.bz2', empty_dirs=True)

  def test_zip(self):
    self.round_trip(archiver('zip'), expected_ext='zip', empty_dirs=False)

  def test_zip_filter(self):
    def do_filter(path):
      return path == 'allowed.txt'

    with temporary_dir() as fromdir:
      touch(os.path.join(fromdir, 'allowed.txt'))
      touch(os.path.join(fromdir, 'disallowed.txt'))

      with temporary_dir() as archivedir:
        archive = archiver('zip').create(fromdir, archivedir, 'archive')
        with temporary_dir() as todir:
          archiver('zip').extract(archive, todir, filter_func=do_filter)
          self.assertEquals(set(['allowed.txt']), self._listtree(todir, empty_dirs=False))

  def test_tar_dereference(self):

    def check_archive_with_flags(archive_format, dereference):
      with temporary_dir() as fromdir:
        filename = os.path.join(fromdir, 'a')
        linkname = os.path.join(fromdir, 'link_to_a')
        touch(filename)
        relative_symlink(filename, linkname)

        with temporary_dir() as archivedir:
          archive = archiver(archive_format).create(fromdir, archivedir, 'archive', dereference=dereference)
          with temporary_dir() as todir:
            archiver(archive_format).extract(archive, todir)
            extracted_linkname = os.path.join(todir, 'link_to_a')
            assertion = self.assertFalse if dereference else self.assertTrue
            assertion(os.path.islink(extracted_linkname))
            assertion(os.path.samefile(extracted_linkname, os.path.join(todir, 'a')))

    check_archive_with_flags('tar', False)
    check_archive_with_flags('tar', True)
    check_archive_with_flags('tgz', False)
    check_archive_with_flags('tgz', True)
    check_archive_with_flags('tbz2', False)
    check_archive_with_flags('tbz2', True)
