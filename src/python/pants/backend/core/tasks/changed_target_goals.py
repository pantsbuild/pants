# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.core.tasks.noop import (NoopExecTask, NoopCompile, NoopTest)
from pants.backend.core.tasks.what_changed import ChangedFileTaskMixin


class ChangedTargetTask(NoopExecTask, ChangedFileTaskMixin):
  """A base class for tasks that find changed targets to act on.

  Frequently other tasks already exist that actually do the desired work eg "compile" or "test".

  A subclass of ChangedTargetTask can be used to create a new goal that runs existing tasks
  on what the SCM indicates are changed targets rather than what the user specifies.

  This is done by scheduling that goal or task, unaltered, and running it as usual, with the
  exception that context.target_roots have been first set to the SCM-derived "changed" targets.

  This is achieved by this task first finding changed targets, then calling context.replace_targets,
  before then asking the round manager to schedule the desired task or goal with a standard
  require_data call. This is done in the prepare() method of this task, after which the run proceeds
  as usual, though with different target roots, until finally getting to this task's execute, which
  is a noop.

  For asking the round manager to schedule a particular goal, it can be helpful to have some known
  product_type in that goal. See noop.py and NoopExecTask for noop tasks that can easily be
  installed in a goal to make it provide some known product type.
  """
  @classmethod
  def register_options(cls, register):
    super(ChangedTargetTask, cls).register_options(register)
    cls.register_change_file_options(register)

  def prepare(self, round_manager):
    super(ChangedTargetTask, self).prepare(round_manager)
    changed = self._changed_targets()
    self.context.replace_targets([self.context.build_graph.get_target(addr) for addr in changed])
    readable = ''.join(sorted('\n\t* {}'.format(addr.reference()) for addr in changed))
    self.context.log.info('Operating on changed {} target(s): {}'.format(len(changed), readable))


class CompileChanged(ChangedTargetTask):
  """Find and compile changed targets."""
  def prepare(self, round_manager):
    super(CompileChanged, self).prepare(round_manager)  # Replaces target roots.
    round_manager.require_data(NoopCompile.product_types()[0])


class TestChanged(ChangedTargetTask):
  """Find and test changed targets."""
  def prepare(self, round_manager):
    super(TestChanged, self).prepare(round_manager) # Replaces target roots.
    round_manager.require_data(NoopTest.product_types()[0])
