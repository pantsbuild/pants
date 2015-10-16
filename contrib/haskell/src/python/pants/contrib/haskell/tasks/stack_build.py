# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.contrib.haskell.tasks.stack_task import StackTask


class StackBuild(StackTask):
  """Build the given Haskell target"""

  @classmethod
  def register_options(cls, register):
    super(StackBuild, cls).register_options(register)
    register('--watch', action='store_true', help='Watch for changes in local files and automatically rebuild.')

  def execute(self):
    if self.get_options().watch:
      extra_args = ["--file-watch"]
    else:
      extra_args = []
    for dir in self.stack_task("build", extra_args):
      pass
