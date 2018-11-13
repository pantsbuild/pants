# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.task.task import Task


class CheckBannedDeps(Task):
  """
  This task ensures that a target does not depend on banned dependencies.
  """

  @classmethod
  def register_options(cls, register):
    super(CheckBannedDeps, cls).register_options(register)
    # If this flag changes, the debug message below should change too.
    register('--skip', type=bool, fingerprint=True, default=True,
      help='Do not perform the operations if this is active')

  @classmethod
  def prepare(cls, options, round_manager):
    super(CheckBannedDeps, cls).prepare(options, round_manager)
    round_manager.require_data('runtime_classpath')

  def execute(self):
    if not self.get_options().skip:
      for target in self.context.targets():
        constraints = target.payload.get_field_value("dependency_constraints")
        if constraints:
          constraints.check_all(target, self.context)
    else:
      self.context.log.debug("Skipping banned dependency checks. To enforce this, enable the --compile-check-banned-deps-skip flag")
