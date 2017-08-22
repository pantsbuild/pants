# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.deprecated import deprecated
from pants.task.task import Task


class Invalidate(Task):
  """Invalidate the entire build."""

  @deprecated(removal_version='1.6.0.dev0',
              hint_message='Use `./pants --cache-ignore ...` instead.')
  def execute(self):
    # TODO(John Sirois): Remove the `root` argument `_build_invalidator` once this deprecation cycle
    # is complete. This is the only caller using the argument:
    #   https://github.com/pantsbuild/pants/issues/4697
    self._build_invalidator(root=True).force_invalidate_all()
