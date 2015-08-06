# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.core.tasks.task import Task
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.util.dirutil import safe_rmtree


def _cautious_rmtree(root):
  real_buildroot = os.path.realpath(os.path.abspath(get_buildroot()))
  real_root = os.path.realpath(os.path.abspath(root))
  if not real_root.startswith(real_buildroot):
    raise TaskError('DANGER: Attempting to delete {}, which is not under the build root!'.format(real_root))
  safe_rmtree(real_root)


class Invalidator(Task):
  """Invalidate the entire build."""

  def execute(self):
    build_invalidator_dir = os.path.join(self.get_options().pants_workdir, 'build_invalidator')
    _cautious_rmtree(build_invalidator_dir)


class Cleaner(Task):
  """Clean all current build products."""

  def execute(self):
    _cautious_rmtree(self.get_options().pants_workdir)
