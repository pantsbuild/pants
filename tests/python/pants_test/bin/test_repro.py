# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from pants.bin.repro import Repro
from pants.util.contextutil import open_tar, temporary_dir
from pants.util.dirutil import safe_mkdir_for


class ReproTest(unittest.TestCase):
  def test_repro(self):
    with temporary_dir() as tmpdir:
      fake_buildroot = os.path.join(tmpdir, 'buildroot')
      def add_file(path, content):
        fullpath = os.path.join(fake_buildroot, path)
        safe_mkdir_for(fullpath)
        with open(fullpath, 'w') as outfile:
          outfile.write(content)

      add_file('.git/foo', 'foo')
      add_file('dist/bar', 'bar')
      add_file('baz.txt', 'baz')
      add_file('qux/quux.txt', 'quux')

      repro_file = os.path.join(tmpdir, 'repro.tar.gz')
      repro = Repro(repro_file, fake_buildroot, ['.git', 'dist'])
      repro.capture(run_info_dict={'foo': 'bar', 'baz': 'qux'})

      extract_dir = os.path.join(tmpdir, 'extract')
      with open_tar(repro_file, 'r:gz') as tar:
        tar.extractall(extract_dir)

      def assert_not_exists(relpath):
        fullpath = os.path.join(extract_dir, relpath)
        self.assertFalse(os.path.exists(fullpath))

      def assert_file(relpath, expected_content=None):
        fullpath = os.path.join(extract_dir, relpath)
        self.assertTrue(os.path.isfile(fullpath))
        if expected_content:
          with open(fullpath, 'r') as infile:
            content = infile.read()
          self.assertEquals(expected_content, content)

      assert_file('baz.txt', 'baz')
      assert_file('qux/quux.txt', 'quux')
      assert_file('repro.sh')

      assert_not_exists('.git')
      assert_not_exists('dist')
