# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.deprecated import deprecated
from pants.task.task import Task


class Invalidate(Task):
  """Invalidate the entire build."""

  @deprecated(removal_version='1.6.0.dev0', hint_message='Use `./pants --force ...` instead.')
  def execute(self):
    self._build_invalidator(root=True).force_invalidate_all()
