# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod
from collections import defaultdict

from pants.backend.core.tasks.task import Task
from pants.base.exceptions import TaskError


class MutexTaskMixin(Task):
  """A mixin that can be subclassed to form a mutual exclusion group of tasks.

  Generally, you'd subclass MutexTaskMixin and override `mutex_base` to return the (abstract) type
  of your mutual exclusion group tasks, for example::

      class LogViewerTaskMixin(MutexTaskMixin):
        '''Pops up an interactive log viewing console.

        Log viewers pop up their console for binary targets they know how to execute and scrape
        logs from.
        '''
        @classmethod
        def mutex_base(cls):
          return LogViewerTaskMixin

  Then all tasks that implemented an interactive log viewer would mix in LogViewerTaskMixin and
  provide concrete implementations for `select_targets` that pick out the binary targets they know
  how to handle and `execute_for` to execute those binaries and scrape their logs.

  Assuming all these tasks were registered under the `logview` goal then each task could be assured
  it would be executed to the exclusion of all other LogViewerTaskMixins in any
  `./pants logview ...` run.
  """

  class NoActivationsError(TaskError):
    """Indicates a mutexed task group had no tasks run."""

  class IncompatibleActivationsError(TaskError):
    """Indicates a mutexed task group had more than one task eligible to run."""

  _implementations = defaultdict(set)

  @classmethod
  def reset_implementations(cls):
    """Resets all mutex implementation registrations.

    Only intended for testing.
    """
    cls._implementations.clear()

  @classmethod
  def mutex_base(cls):
    """Returns the root class in a mutex group.

    Members of the group will all mix in this class and it should implement this method concretely
    to return itself.
    """
    raise NotImplementedError()

  @classmethod
  def prepare(cls, options, round_manager):
    super(MutexTaskMixin, cls).prepare(options, round_manager)

    cls._implementations[cls.mutex_base()].add(cls)

  @classmethod
  def select_targets(cls, target):
    """Returns `True` if the given target is operated on by this mutex group member."""
    raise NotImplementedError()

  @classmethod
  def _selected_by_other_impl(cls, target):
    for impl in cls._implementations[cls.mutex_base()]:
      if impl != cls and impl.select_targets(target):
        return True
    return False

  @abstractmethod
  def execute_for(self, targets):
    """Executes the current mutex member with its selected targets.

    When this method is called, its an indication that the current mutex member is the only member
    active in this pants run.

    :param targets: All the targets reachable in this run selected by this mutex member's
                    `select_targets` method.
    """

  def execute(self):
    targets = self._require_homogeneous_targets(self.select_targets, self._selected_by_other_impl)
    if targets:
      return self.execute_for(targets)
    # Else a single other mutex impl is executing.

  def _require_homogeneous_targets(self, accept_predicate, reject_predicate):
    """Ensures that there is no ambiguity in the context according to the given predicates.

    If any targets in the context satisfy the accept_predicate, and no targets satisfy the
    reject_predicate, returns the accepted targets.

    If no targets satisfy the accept_predicate, returns None.

    Otherwise throws TaskError.
    """
    if len(self.context.target_roots) == 0:
      raise self.NoActivationsError('No target specified.')

    accepted = self.context.targets(accept_predicate)
    rejected = self.context.targets(reject_predicate)
    if len(accepted) == 0:
      # no targets were accepted, regardless of rejects
      return None
    elif len(rejected) == 0:
      # we have at least one accepted target, and no rejected targets
      return accepted
    else:
      # both accepted and rejected targets
      # TODO: once https://github.com/pantsbuild/pants/issues/425 lands, we should add
      # language-specific flags that would resolve the ambiguity here
      def render_target(target):
        return '{} (a {})'.format(target.address.reference(), target.type_alias)
      raise self.IncompatibleActivationsError('Mutually incompatible targets specified: {} vs {} '
                                              '(and {} others)'
                                              .format(render_target(accepted[0]),
                                                      render_target(rejected[0]),
                                                      len(accepted) + len(rejected) - 2))
