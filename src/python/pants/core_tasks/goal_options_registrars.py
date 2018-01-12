# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.goal.goal_options_registrar import GoalOptionsRegistrar


"""GoalOptionsRegistrar subclasses for various core goals."""


class _CodeCheckerGoalOptionsRegistrarBase(GoalOptionsRegistrar):
  """Registers recursive options on all tasks in the lint/fmt goals."""

  @classmethod
  def register_options(cls, register):
    register('--skip', type=bool, default=False, fingerprint=True, recursive=True,
             help='Skip task.')
    register('--transitive', type=bool, default=True, fingerprint=True, recursive=True,
             help="If false, act only on the targets directly specified on the command line. "
                  "If true, act on the transitive dependency closure of those targets.")


class LintGoalOptionsRegistrar(_CodeCheckerGoalOptionsRegistrarBase):
  options_scope = 'lint'


class FmtGoalOptionsRegistrar(_CodeCheckerGoalOptionsRegistrarBase):
  options_scope = 'fmt'