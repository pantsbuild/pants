# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from abc import abstractproperty
import os

from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.backend.core.tasks.task import QuietTaskMixin, Task, TaskBase
from pants.base.exceptions import TaskError
from pants.java import util
from pants.java.distribution.distribution import Distribution
from pants.java.executor import SubprocessExecutor
from pants.java.nailgun_executor import NailgunExecutor


class NailgunTaskBase(TaskBase, JvmToolTaskMixin):

  _DAEMON_OPTION_PRESENT = False

  @staticmethod
  def killall(logger=None, everywhere=False):
    """Kills all nailgun servers launched by pants in the current repo.

    Returns ``True`` if all nailguns were successfully killed, ``False`` otherwise.

    :param logger: a callable that accepts a message string describing the killed nailgun process
    :param bool everywhere: ``True`` to kill all nailguns servers launched by pants on this machine
    """
    if not NailgunExecutor.killall:
      return False
    else:
      return NailgunExecutor.killall(logger=logger, everywhere=everywhere)

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    if not NailgunTaskBase._DAEMON_OPTION_PRESENT:
      option_group.parser.add_option("--ng-daemons", "--no-ng-daemons", dest="nailgun_daemon",
                                     default=True, action="callback", callback=mkflag.set_bool,
                                     help="[%default] Use nailgun daemons to execute java tasks.")
      NailgunTaskBase._DAEMON_OPTION_PRESENT = True

  def __init__(self, *args, **kwargs):
    super(NailgunTaskBase, self).__init__(*args, **kwargs)
    self._executor_workdir = os.path.join(self.context.config.getdefault('pants_workdir'), 'ng',
                                          self.__class__.__name__)
    self._nailgun_bootstrap_key = 'nailgun'
    self.register_jvm_tool(self._nailgun_bootstrap_key, ['//:nailgun-server'])
    self.set_distribution()  # Use default until told otherwise.
    # TODO: Choose default distribution based on options.

  def set_distribution(self, minimum_version=None, maximum_version=None, jdk=False):
    try:
      self._dist = Distribution.cached(minimum_version=minimum_version,
                                       maximum_version=maximum_version, jdk=jdk)
    except Distribution.Error as e:
      raise TaskError(e)

  @abstractproperty
  def config_section(self):
    """NailgunTask must be sub-classed to provide a config section name"""

  @property
  def nailgun_is_enabled(self):
    return self.context.config.getbool(self.config_section, 'use_nailgun', default=True)

  def create_java_executor(self):
    """Create java executor that uses this task's ng daemon, if allowed.

    Call only in execute() or later. TODO: Enforce this.
    """
    if self.nailgun_is_enabled and self.context.options.nailgun_daemon:
      classpath = os.pathsep.join(self.tool_classpath(self._nailgun_bootstrap_key))
      client = NailgunExecutor(self._executor_workdir, classpath, distribution=self._dist)
    else:
      client = SubprocessExecutor(self._dist)
    return client

  @property
  def jvm_args(self):
    """Default jvm args the nailgun will be launched with.

    By default no special jvm args are used.  If a value for ``jvm_args`` is specified in pants.ini
    globally in the ``DEFAULT`` section or in the ``nailgun`` section, then that list will be used.
    """
    return self.context.config.getlist('nailgun', 'jvm_args', default=[])

  def runjava(self, classpath, main, jvm_options=None, args=None, workunit_name=None,
              workunit_labels=None):
    """Runs the java main using the given classpath and args.

    If --no-ng-daemons is specified then the java main is run in a freshly spawned subprocess,
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


class NailgunKillall(Task, QuietTaskMixin):
  """A task to manually kill nailguns."""
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(NailgunKillall, cls).setup_parser(option_group, args, mkflag)
    option_group.add_option(mkflag("everywhere"), dest="ng_killall_everywhere",
                            default=False, action="store_true",
                            help="[%default] Kill all nailguns servers launched by pants for "
                                 "all workspaces on the system.")

  def execute(self):
    NailgunTaskBase.killall(everywhere=self.context.options.ng_killall_everywhere)
