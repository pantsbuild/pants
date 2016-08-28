# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import tarfile
import unittest

from pants.util.dirutil import safe_delete, safe_mkdtemp, safe_rmtree, touch
from pants.util.tarutil import TarFile


class TarutilTest(unittest.TestCase):
  def setUp(self):
    self.basedir = safe_mkdtemp()

    self.file_list = ['a', 'b', 'c']
    self.file_tar = os.path.join(self.basedir, 'test.tar')

    with TarFile.open(self.file_tar, mode='w') as tar:
      for f in self.file_list:
        full_path = os.path.join(self.basedir, f)
        touch(full_path)
        tar.add(full_path, f)
        safe_delete(full_path)

  def tearDown(self):
    safe_rmtree(self.basedir)

  def inject_corruption(self):
    with open(self.file_tar, 'r+w') as fp:
      content = fp.read()
      fp.seek(0)
      # Replace 8 bytes of good data with garbage.
      fp.write(content[:512+148] + 'aaaaaaaa' + content[512+156:])

  def extract_tar(self, path, **kwargs):
    with TarFile.open(self.file_tar, mode='r', **kwargs) as tar:
      tar.extractall(path=self.basedir)

  def test_invalid_header_errorlevel_0(self):
    self.inject_corruption()
    self.assertIsNone(self.extract_tar(self.file_tar, errorlevel=0))

  def test_invalid_header_errorlevel_1(self):
    self.inject_corruption()
    with self.assertRaises(tarfile.ReadError):
      self.extract_tar(self.file_tar, errorlevel=1)

  def test_extract(self):
    self.extract_tar(self.file_tar, errorlevel=2)
    self.assertEqual(
      set(os.listdir(self.basedir)),
      set([os.path.relpath(self.file_tar, self.basedir)] + self.file_list))
