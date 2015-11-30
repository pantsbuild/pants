# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from functools import partial

from pants.bin.repro import Repro
from pants.fs.archive import TGZ
from pants.util.contextutil import open_tar, temporary_dir
from pants_test.bin.repro_mixin import ReproMixin


class ReproTest(unittest.TestCase, ReproMixin):
  def test_repro(self):
    """Verify that Repro object creates expected tar.gz file"""
    with temporary_dir() as tmpdir:
      fake_buildroot = os.path.join(tmpdir, 'buildroot')

      add_file = partial(self.add_file, fake_buildroot)
      add_file('.git/foo', 'foo')
      add_file('dist/bar', 'bar')
      add_file('baz.txt', 'baz')
      add_file('qux/quux.txt', 'quux')

      repro_file = os.path.join(tmpdir, 'repro.tar.gz')
      repro = Repro(repro_file, fake_buildroot, ['.git', 'dist'])
      repro.capture(run_info_dict={'foo': 'bar', 'baz': 'qux'})

      extract_dir = os.path.join(tmpdir, 'extract')
      TGZ.extract(repro_file, extract_dir)

      assert_file = partial(self.assert_file, extract_dir)
      assert_file('baz.txt', 'baz')
      assert_file('qux/quux.txt', 'quux')
      assert_file('repro.sh')

      assert_not_exists = partial(self.assert_not_exists, extract_dir)
      assert_not_exists('.git')
      assert_not_exists('dist')
