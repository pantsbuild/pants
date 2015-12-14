# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.task.task import Task
from pants.util.dirutil import safe_rmtree


class Clean(Task):
  """Delete all build products, creating a clean workspace."""

  def execute(self):
    safe_rmtree(self.get_options().pants_workdir)
