# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from functools import partial

from pants.base.build_root import BuildRoot
from pants.bin.repro import Reproducer
from pants.fs.archive import TGZ
from pants.util.contextutil import pushd, temporary_dir
from pants_test.bin.repro_mixin import ReproMixin
from pants_test.subsystem.subsystem_util import subsystem_instance


class ReproOptionsTest(unittest.TestCase, ReproMixin):

  def test_ignore_dir(self):
    """Verify that passing --repro-ignore option ignores the directory"""

    # Buildroot is is based on your cwd so we need to step into a fresh
    # directory for repro to look at.
    root_instance = BuildRoot()
    with temporary_dir() as build_root:
      with root_instance.temporary(build_root):
        with pushd(build_root):
          with temporary_dir() as capture_dir:
            add_file = partial(self.add_file, build_root)
            add_file('pants.ini', '')
            add_file('.git/foo', 'foo')
            add_file('dist/bar', 'bar')
            add_file('foo/bar', 'baz')
            add_file('src/test1', 'test1')
            add_file('src/test2', 'test1')

            repro_file = os.path.join(capture_dir, 'repro.tar.gz')
            options = {
              'repro': dict(
                capture=repro_file,
                ignore=['src'],
            )}
            with subsystem_instance(Reproducer, **options) as repro_sub:
              repro = repro_sub.create_repro()  # This is normally called in pants_exe
              repro.capture(run_info_dict={})

              extract_loc = os.path.join(capture_dir, 'extract')
              TGZ.extract(repro_file, extract_loc)

              assert_file = partial(self.assert_file, extract_loc)
              assert_file('foo/bar', 'baz')

              assert_not_exists = partial(self.assert_not_exists, extract_loc)
              assert_not_exists('.git')
              assert_not_exists('src')
