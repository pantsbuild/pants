# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.core.tasks.task import Task, TaskBase
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.base.exceptions import TaskError
from pants.java import util
from pants.java.distribution.distribution import DistributionLocator
from pants.java.executor import SubprocessExecutor
from pants.java.nailgun_executor import NailgunExecutor, NailgunProcessGroup


class NailgunTaskBase(JvmToolTaskMixin, TaskBase):
  ID_PREFIX = 'ng'

  @classmethod
  def register_options(cls, register):
    super(NailgunTaskBase, cls).register_options(register)
    register('--use-nailgun', action='store_true', default=True,
             help='Use nailgun to make repeated invocations of this task quicker.')
    register('--nailgun-timeout-seconds', advanced=True, default=10,
             help='Timeout (secs) for nailgun startup.')
    register('--nailgun-connect-attempts', advanced=True, default=5,
             help='Max attempts for nailgun connects.')
    cls.register_jvm_tool(register,
                          'nailgun-server',
                          classpath=[
                            JarDependency(org='com.martiansoftware',
                                          name='nailgun-server',
                                          rev='0.9.1'),
                          ])

  @classmethod
  def global_subsystems(cls):
    return super(NailgunTaskBase, cls).global_subsystems() + (DistributionLocator,)

  def __init__(self, *args, **kwargs):
    super(NailgunTaskBase, self).__init__(*args, **kwargs)

    id_tuple = (self.ID_PREFIX, self.__class__.__name__)

    self._identity = '_'.join(id_tuple)
    self._executor_workdir = os.path.join(self.context.options.for_global_scope().pants_workdir,
                                          *id_tuple)
    self.set_distribution()    # Use default until told otherwise.
    # TODO: Choose default distribution based on options.

  def set_distribution(self, minimum_version=None, maximum_version=None, jdk=False):
    try:
      self._dist = DistributionLocator.cached(minimum_version=minimum_version,
                                              maximum_version=maximum_version, jdk=jdk)
    except DistributionLocator.Error as e:
      raise TaskError(e)

  def create_java_executor(self):
    """Create java executor that uses this task's ng daemon, if allowed.

    Call only in execute() or later. TODO: Enforce this.
    """
    if self.get_options().use_nailgun:
      classpath = os.pathsep.join(self.tool_classpath('nailgun-server'))
      return NailgunExecutor(self._identity,
                             self._executor_workdir,
                             classpath,
                             self._dist,
                             connect_timeout=self.get_options().nailgun_timeout_seconds,
                             connect_attempts=self.get_options().nailgun_connect_attempts)
    else:
      return SubprocessExecutor(self._dist)

  def runjava(self, classpath, main, jvm_options=None, args=None, workunit_name=None,
              workunit_labels=None, workunit_log_config=None):
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
                               workunit_labels=workunit_labels,
                               workunit_log_config=workunit_log_config)
    except executor.Error as e:
      raise TaskError(e)


# TODO(John Sirois): This just prevents ripple - maybe inline
class NailgunTask(NailgunTaskBase, Task): pass


class NailgunKillall(Task):
  """A task to manually kill nailguns."""

  @classmethod
  def register_options(cls, register):
    super(NailgunKillall, cls).register_options(register)
    register('--everywhere', default=False, action='store_true',
             help='Kill all nailguns servers launched by pants for all workspaces on the system.')

  def execute(self):
    NailgunProcessGroup().killall(everywhere=self.get_options().everywhere)
