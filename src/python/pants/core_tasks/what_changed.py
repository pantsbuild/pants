# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.task.changed_file_task_mixin import ChangedFileTaskMixin
from pants.task.console_task import ConsoleTask


class WhatChanged(ChangedFileTaskMixin, ConsoleTask):
  """Emits the targets that have been modified since a given commit."""

  @classmethod
  def register_options(cls, register):
    super(WhatChanged, cls).register_options(register)
    cls.register_change_file_options(register)
    register('--files', action='store_true', default=False,
             help='Show changed files instead of the targets that own them.')

  def console_output(self, _):
    spec_excludes = self.get_options().spec_excludes
    change_calculator = self.change_calculator(self.get_options(),
                                               self.context.address_mapper,
                                               self.context.build_graph,
                                               scm=self.context.scm,
                                               workspace=self.context.workspace,
                                               spec_excludes=spec_excludes)
    if self.get_options().files:
      for f in sorted(change_calculator.changed_files()):
        yield f
    else:
      for addr in sorted(change_calculator.changed_target_addresses()):
        yield addr.spec
