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


class NailgunUtil(object):
  """Contains methods that don't use any task-related data except for the parameters."""

  @staticmethod
  def get_distribution(minimum_version=None, maximum_version=None, jdk=False):
    try:
      return Distribution.cached(minimum_version=minimum_version, maximum_version=maximum_version, jdk=jdk)
    except Distribution.Error as e:
      raise TaskError(e)

  @staticmethod
  def killall(everywhere=False):
    """Kills all nailgun servers launched by pants in the current repo.

    Returns ``True`` if all nailguns were successfully killed, ``False`` otherwise.

    :param bool everywhere: ``True`` to kill all nailguns servers launched by pants on this machine
    """
    if not NailgunExecutor.killall:
      return False
    else:
      return NailgunExecutor.killall(everywhere=everywhere)


class NailgunTaskBase(JvmToolTaskMixin, TaskBase):

  @classmethod
  def register_options(cls, register):
    super(NailgunTaskBase, cls).register_options(register)
    cls.register_jvm_tool(register, 'nailgun-server')
    register('--use-nailgun', action='store_true', default=True,
             help='Use nailgun to make repeated invocations of this task quicker.')

  def __init__(self, *args, **kwargs):
    super(NailgunTaskBase, self).__init__(*args, **kwargs)
    self._default_executor_workdir = self._get_executor_workdir(self.__class__.__name__)
    # TODO: Choose default distribution based on options.

  def _get_executor_workdir(self, name):
    return os.path.join(self.context.options.for_global_scope().pants_workdir, 'ng', name)

  @property
  def nailgun_is_enabled(self):
    return self.get_options().use_nailgun

  def create_java_executor(self, executor_workdir_name=None, dist=NailgunUtil.get_distribution()):
    """Create java executor that uses this task's ng daemon, if allowed.

    Call only in execute() or later. TODO: Enforce this.
    """
    if self.nailgun_is_enabled:
      if executor_workdir_name is None:
        executor_workdir = self._default_executor_workdir
      else:
        executor_workdir = self._get_executor_workdir(executor_workdir_name)
      classpath = os.pathsep.join(self.tool_classpath('nailgun-server'))
      return NailgunExecutor(executor_workdir, classpath, distribution=dist)
    else:
      return SubprocessExecutor(dist)

  def runjava(self, classpath, main, jvm_options=None, args=None, executor_workdir_name=None,
              minimum_version=None, maximum_version=None, jdk=False,
              workunit_name=None, workunit_labels=None):
    """Runs the java main using the given classpath and args.

    If --no-use-nailgun is specified then the java main is run in a freshly spawned subprocess,
    otherwise a persistent nailgun server dedicated to this Task subclass is used to speed up
    amortized run times.
    """
    dist = NailgunUtil.get_distribution(minimum_version=minimum_version, maximum_version=maximum_version, jdk=jdk)
    executor = self.create_java_executor(executor_workdir_name, dist)

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
    NailgunUtil.killall(everywhere=self.get_options().everywhere)
