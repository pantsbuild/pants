# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.task.task import Task
from pants.util.dirutil import safe_rmtree


class Invalidate(Task):
  """Invalidate the entire build."""

  def execute(self):
    build_invalidator_dir = os.path.join(self.get_options().pants_workdir, 'build_invalidator')
    safe_rmtree(build_invalidator_dir)
