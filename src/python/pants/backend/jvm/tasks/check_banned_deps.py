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

  @staticmethod
  def relevant_targets(target):
    """
    Modify this method when the criteria changes
    (e.g. the target itself should be included in the checks).
    """
    return set(target.dependencies)

  def execute(self):
    if not self.get_options().skip:
      self.pairs_checked = 0
      for target in self.context.target_roots:
        constraint_declaration = target.payload.get_field_value("dependency_constraints")
        if constraint_declaration:
          relevant_targets = CheckBannedDeps.relevant_targets(target)
          for constraint in constraint_declaration.constraints:
            for target_under_test in relevant_targets:
              constraint.check_target(target, self.context, target_under_test)
    else:
      self.context.log.debug("Skipping banned dependency checks. To enforce this, enable the --no-compile-check-banned-deps-skip flag")
