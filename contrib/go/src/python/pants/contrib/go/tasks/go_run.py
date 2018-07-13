# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.base.exceptions import TaskError
from pants.process.xargs import Xargs

from pants.contrib.go.tasks.go_task import GoTask


class GoRun(GoTask):
  """Runs an executable Go binary."""

  @classmethod
  def supports_passthru_args(cls):
    return True

  @classmethod
  def prepare(cls, options, round_manager):
    super(GoRun, cls).prepare(options, round_manager)
    round_manager.require_data('exec_binary')

  def execute(self):
    target = self.require_single_root_target()
    if self.is_binary(target):
      binary_path = self.context.products.get_data('exec_binary')[target]
      # TODO(cgibb): Wrap with workunit and stdout/stderr plumbing.
      res = Xargs.subprocess([binary_path]).execute(self.get_passthru_args())
      if res != 0:
        raise TaskError('{bin} exited non-zero ({res})'
                        .format(bin=os.path.basename(binary_path), res=res))
