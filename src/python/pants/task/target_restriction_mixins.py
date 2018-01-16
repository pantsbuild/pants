# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.task.goal_options_mixin import GoalOptionsRegistrar


class HasTransitiveOptionMixin(object):
  """A mixin for tasks that have a --transitive option.

  Some tasks must always act on the entire dependency closure. E.g., when compiling, one must
  compile all of a target's dependencies before compiling that target.

  Other tasks must always act only on the target roots (the targets explicitly specified by the
  user on the command line). E.g., when finding paths between two user-specified targets.

  Still other tasks may optionally act on either the target roots or the entire closure,
  as the user prefers in each case. E.g., when invoking a linter. This mixin supports such tasks.

  Note that this mixin doesn't actually register the --transitive option. It assumes that this
  option was registered on the task (either directly or recursively from its goal).
  """

  def get_targets(self, predicate=None):
    if self.get_options().transitive:
      return self.context.targets(predicate)
    else:
      return filter(predicate, self.context.target_roots)


class HasSkipOptionMixin(object):
  """A mixin for tasks that have a --skip option.

  Some tasks may be skipped during certain usages. E.g., you may not want to apply linters
  while developing.  This mixin supports such tasks.

  Note that this mixin doesn't actually register the --skip option. It assumes that this
  option was registered on the task (either directly or recursively from its goal).
  """

  def get_targets(self, predicate=None):
    if self.get_options().skip:
      self.context.log.info('Skipping {}.'.format(self.options_scope))
      return []
    else:
      return super(HasSkipOptionMixin, self).get_targets(predicate)


# Note order of superclasses - it correctly ensures --skip is checked first.
class HasSkipAndTransitiveOptionsMixin(HasSkipOptionMixin, HasTransitiveOptionMixin):
  """A mixin for tasks that have a --transitive and a --skip option."""
  pass


class SkipAndTransitiveOptionsRegistrarBase(GoalOptionsRegistrar):
  """Shared base class for goal-level registrars of --skip and --transitive."""

  @classmethod
  def register_options(cls, register):
    register('--skip', type=bool, default=False, fingerprint=True, recursive=True,
             help='Skip task.')
    register('--transitive', type=bool, default=True, fingerprint=True, recursive=True,
             help="If false, act only on the targets directly specified on the command line. "
                  "If true, act on the transitive dependency closure of those targets.")
