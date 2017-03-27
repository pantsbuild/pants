# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.contrib.go.tasks.go_fmt_task_base import GoFmtTaskBase


class GoFmt(GoFmtTaskBase):
  """Format Go code using gofmt."""

  def execute(self):
    with self.go_fmt_invalid_targets(['-w']) as output:
      if output:
        self.context.logger.info(output)
