# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.task.changed_file_task_mixin import ChangedFileTaskMixin
from pants.task.noop_exec_task import NoopExecTask


logger = logging.getLogger(__name__)


class ChangedTargetTask(ChangedFileTaskMixin, NoopExecTask):
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

  @classmethod
  def alternate_target_roots(cls, options, address_mapper, build_graph):
    change_calculator = cls.change_calculator(
      options,
      address_mapper,
      build_graph)
    changed_addresses = change_calculator.changed_target_addresses()
    readable = ''.join(sorted('\n\t* {}'.format(addr.reference()) for addr in changed_addresses))
    logger.info('Operating on changed {} target(s): {}'.format(len(changed_addresses), readable))
    return [build_graph.get_target(addr) for addr in changed_addresses]
