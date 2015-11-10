# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
from functools import partial

from pants.backend.core.tasks.clean import Cleaner
from pants.bin.repro import Reproducer
from pants.util.contextutil import open_tar, pushd, temporary_dir
from pants_test.bin.repro_mixin import ReproMixin
from pants_test.tasks.task_test_base import TaskTestBase


class ReproOptionsTest(TaskTestBase, ReproMixin):

  @classmethod
  def task_type(cls):
    return Cleaner

  def test_ignore_dir(self):
    """Verify that passing --repro-ignore option ignores the directory"""

    # Buildroot is is based on your cwd so we need to step into a fresh
    # directory for repro to look at.
    with pushd(self.build_root):
      with temporary_dir() as capture_dir:

        add_file = partial(self.add_file, self.build_root)
        add_file('pants.ini', '')
        add_file('.git/foo', 'foo')
        add_file('dist/bar', 'bar')
        add_file('foo/bar', 'baz')
        add_file('src/test1', 'test1')
        add_file('src/test2', 'test1')

        repro_file = os.path.join(capture_dir, 'repro.tar.gz')
        self.set_options_for_scope(Reproducer.options_scope,
                                   capture=repro_file,
                                   ignore=['src'],
                                   pants_distdir='dist')

        self.create_task(self.context())
        repro = Reproducer.global_instance().create_repro()
        repro.capture(run_info_dict={'foo': 'bar', 'baz': 'qux'})

        # clean_task.execute()

        extract_loc = os.path.join(capture_dir, 'extract')
        with open_tar(repro_file, 'r:gz') as tar:
          tar.extractall(extract_loc)

        assert_file = partial(self.assert_file, extract_loc)
        assert_file('foo/bar', 'baz')

        assert_not_exists = partial(self.assert_not_exists, extract_loc)
        assert_not_exists('.git')
        assert_not_exists('src')
