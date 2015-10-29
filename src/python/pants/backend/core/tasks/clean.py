# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.core.tasks.task import Task
from pants.base.build_environment import PANTS_WORKDIR_SUFFIX
from pants.base.exceptions import TaskError
from pants.util.dirutil import safe_rmtree


def _cautious_get_working_directory(task):
  """Check that working directory ends with right suffix before make destructive actions"""
  workdir = task.get_options().pants_workdir
  if not workdir.endswith(PANTS_WORKDIR_SUFFIX):
    raise TaskError('DANGER: Attempting to use working directory {}, which is not ends with \'.pants.d\'!'
                    .format(workdir))
  return workdir


class Invalidator(Task):
  """Invalidate the entire build."""

  def execute(self):
    build_invalidator_dir = os.path.join(_cautious_get_working_directory(self), 'build_invalidator')
    safe_rmtree(build_invalidator_dir)


class Cleaner(Task):
  """Clean all current build products."""

  def execute(self):
    safe_rmtree(_cautious_get_working_directory(self))
