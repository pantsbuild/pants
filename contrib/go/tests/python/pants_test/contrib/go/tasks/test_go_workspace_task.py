# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from itertools import chain

from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir, touch
from pants_test.tasks.task_test_base import TaskTestBase

from pants.contrib.go.tasks.go_workspace_task import GoWorkspaceTask


class GoWorkspaceTaskTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return GoWorkspaceTask

  def test_remove_unused_links(self):
    with temporary_dir() as d:
      dpath = lambda p: os.path.join(d, p)
      safe_mkdir(dpath('foo'))
      safe_mkdir(dpath('bar'))
      touch(dpath('f'))
      for l in ('l1', 'foo/l2', 'bar/l3'):
        # Create symlinks to directories.
        os.symlink('/', dpath(l))
      for l in ('l4', 'foo/l5', 'bar/l6'):
        # Create symlinks to files.
        os.symlink(dpath('f'), dpath(l))

      required_links = [dpath('foo/l2'), dpath('l4'), dpath('bar/l6')]
      GoWorkspaceTask.remove_unused_links(d, required_links)

      for p in chain(required_links, ['f']):
        self.assertTrue(os.path.exists(dpath(p)))

      self.assertFalse(os.path.exists(dpath('l1')))
      self.assertFalse(os.path.exists(dpath('bar/l3')))
      self.assertFalse(os.path.exists(dpath('foo/l5')))
