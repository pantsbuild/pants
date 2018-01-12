# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


class TransitiveOptionMixin(object):
  """A mixin for tasks that optionally act on the entire dependency closure of the target roots.

  Some tasks must always act on the entire closure. E.g., when compiling, one must compile all
  of a target's dependencies before compiling that target.

  Other tasks must always act only on the target roots (the targets explicitly specified by the
  user on the command line). E.g., when finding paths between two user-specified targets.

  Still other tasks may optionally act on either the target roots or the entire closure,
  as the user prefers in each case. E.g., when invoking a linter. This mixin supports such tasks.
  """
  # Subclasses may override to provide a different default.
  transitive_default = False

  @classmethod
  def register_options(cls, register):
    super(TransitiveOptionMixin, cls).register_options(register)
    register('--transitive', default=cls.transitive_default, type=bool,
             help='Act on the transitive dependencies of targets specified on the command line. '
                  'Otherwise, act only on the targets directly specified on the command line.')

  def targets_to_act_on(self, predicate=None):
    if self.get_options().transitive:
      return self.context.targets(predicate)
    else:
      return filter(predicate, self.context.target_roots)
