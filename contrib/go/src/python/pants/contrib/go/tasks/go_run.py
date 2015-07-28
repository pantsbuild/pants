# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.exceptions import TaskError
from pants.process.xargs import Xargs

from pants.contrib.go.targets.go_binary import GoBinary
from pants.contrib.go.tasks.go_task import GoTask


class GoRun(GoTask):

  @classmethod
  def prepare(cls, options, round_manager):
    super(GoRun, cls).prepare(options, round_manager)
    round_manager.require_data('go_binary')

  @staticmethod
  def is_binary(target):
    return isinstance(target, GoBinary)

  def execute(self):
    targets = self.context.targets(self.is_binary)
    for target in targets:
      binary_path = self.context.products.get_data('go_binary')[target]
      res = Xargs.subprocess([binary_path]).execute([])
      if res != 0:
        raise TaskError('{bin} exited non-zero ({res})'
                        .format(bin=os.path.basename(binary_path), res=res))
