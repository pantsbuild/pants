# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.exceptions import TaskError

from pants.contrib.go.tasks.go_fmt_task_base import GoFmtTaskBase


class GoCheckstyle(GoFmtTaskBase):
  """Checks Go code matches gofmt style."""

  deprecated_options_scope = 'compile.gofmt'
  deprecated_options_scope_removal_version = '1.5.0.dev0'

  @classmethod
  def register_options(cls, register):
    super(GoCheckstyle, cls).register_options(register)
    register('--skip', type=bool, fingerprint=True, help='Skip checkstyle.')

  def execute(self):
    if self.get_options().skip:
      return
    with self.go_fmt_invalid_targets(['-d']) as output:
      if output:
        self.context.log.error(output)
        raise TaskError('Found style errors. Use `./pants fmt` to fix.')
