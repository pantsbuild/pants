# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.core.tasks.task import Task, TaskBase
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.base.exceptions import TaskError
from pants.java import util
from pants.java.distribution.distribution import Distribution
from pants.java.executor import SubprocessExecutor
from pants.java.nailgun_executor import NailgunExecutor


class NailgunTaskBase(TaskBase, JvmToolTaskMixin):

  @staticmethod
  def killall(everywhere=False):
    """Kills all nailgun servers launched by pants in the current repo.

    Returns ``True`` if all nailguns were successfully killed, ``False`` otherwise.

    :param logger: a callable that accepts a message string describing the killed nailgun process
    :param bool everywhere: ``True`` to kill all nailguns servers launched by pants on this machine
    """
    if not NailgunExecutor.killall:
      return False
    else:
      return NailgunExecutor.killall(everywhere=everywhere)

  @classmethod
  def register_options(cls, register):
    super(NailgunTaskBase, cls).register_options(register)
    cls.register_jvm_tool(register, 'nailgun-server')
    register('--use-nailgun', action='store_true', default=True,
             help='Use nailgun to make repeated invocations of this task quicker.')

  def __init__(self, *args, **kwargs):
    super(NailgunTaskBase, self).__init__(*args, **kwargs)
    self._executor_workdir = os.path.join(self.context.options.for_global_scope().pants_workdir,
                                          'ng', self.__class__.__name__)
    self.set_distribution()  # Use default until told otherwise.
    # TODO: Choose default distribution based on options.

  def set_distribution(self, minimum_version=None, maximum_version=None, jdk=False):
    try:
      self._dist = Distribution.cached(minimum_version=minimum_version,
                                       maximum_version=maximum_version, jdk=jdk)
    except Distribution.Error as e:
      raise TaskError(e)

  @property
  def nailgun_is_enabled(self):
    return self.get_options().use_nailgun

  def create_java_executor(self):
    """Create java executor that uses this task's ng daemon, if allowed.

    Call only in execute() or later. TODO: Enforce this.
    """
    if self.nailgun_is_enabled:
      classpath = os.pathsep.join(self.tool_classpath('nailgun-server'))
      client = NailgunExecutor(self._executor_workdir, classpath, distribution=self._dist)
    else:
      client = SubprocessExecutor(self._dist)
    return client

  def runjava(self, classpath, main, jvm_options, args=None, workunit_name=None,
              workunit_labels=None):
    """Runs the java main using the given classpath and args.

    If --no-use-nailgun is specified then the java main is run in a freshly spawned subprocess,
    otherwise a persistent nailgun server dedicated to this Task subclass is used to speed up
    amortized run times.
    """
    executor = self.create_java_executor()
    try:
      return util.execute_java(classpath=classpath,
                               main=main,
                               jvm_options=jvm_options,
                               args=args,
                               executor=executor,
                               workunit_factory=self.context.new_workunit,
                               workunit_name=workunit_name,
                               workunit_labels=workunit_labels)
    except executor.Error as e:
      raise TaskError(e)


class NailgunTask(NailgunTaskBase, Task):
  # TODO(John Sirois): This just prevents ripple - maybe inline
  pass


class NailgunKillall(Task):
  """A task to manually kill nailguns."""
  @classmethod
  def register_options(cls, register):
    super(NailgunKillall, cls).register_options(register)
    register('--everywhere', default=False, action='store_true',
             help='Kill all nailguns servers launched by pants for all workspaces on the system.')

  def execute(self):
    NailgunTaskBase.killall(everywhere=self.get_options().everywhere)
