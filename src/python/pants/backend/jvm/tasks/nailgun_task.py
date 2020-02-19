# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from enum import Enum

from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.java import util
from pants.java.executor import SubprocessExecutor
from pants.java.jar.jar_dependency import JarDependency
from pants.java.nailgun_executor import NailgunExecutor, NailgunProcessGroup
from pants.process.subprocess import Subprocess
from pants.task.task import Task, TaskBase


class NailgunTaskBase(JvmToolTaskMixin, TaskBase):
    ID_PREFIX = "ng"

    class ExecutionStrategy(Enum):
        nailgun = "nailgun"
        subprocess = "subprocess"
        hermetic = "hermetic"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--execution-strategy",
            default=cls.ExecutionStrategy.nailgun,
            type=cls.ExecutionStrategy,
            help="If set to nailgun, nailgun will be enabled and repeated invocations of this "
            "task will be quicker. If set to subprocess, then the task will be run without "
            "nailgun. Hermetic execution is an experimental subprocess execution framework.",
        )
        register(
            "--nailgun-subprocess-startup-timeout",
            advanced=True,
            default=10,
            type=float,
            help="The time (secs) to wait for a nailgun subprocess to start.",
        )
        register(
            "--nailgun-timeout-seconds",
            advanced=True,
            default=10,
            type=float,
            help="The time (secs) to wait for a nailgun subprocess to start writing to stdout.",
        )
        register(
            "--nailgun-connect-attempts",
            advanced=True,
            default=5,
            type=int,
            help="Max attempts for nailgun connects.",
        )
        cls.register_jvm_tool(
            register,
            "nailgun-server",
            classpath=[
                JarDependency(org="com.martiansoftware", name="nailgun-server", rev="0.9.1"),
            ],
        )

    @property
    def execution_strategy(self):
        return self.get_options().execution_strategy

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (Subprocess.Factory,)

    def __init__(self, *args, **kwargs):
        """
        :API: public
        """
        super().__init__(*args, **kwargs)

        id_tuple = (self.ID_PREFIX, self.__class__.__name__)

        self._identity = "_".join(id_tuple)
        self._executor_workdir = os.path.join(
            self.context.options.for_global_scope().pants_workdir, *id_tuple
        )

    def create_java_executor(self, dist=None, force_subprocess=False):
        """Create java executor that uses this task's ng daemon, if allowed.

        Call only in execute() or later. TODO: Enforce this.
        """
        dist = dist or self.dist
        if self.execution_strategy == self.ExecutionStrategy.nailgun and not force_subprocess:
            classpath = os.pathsep.join(self.tool_classpath("nailgun-server"))
            return NailgunExecutor(
                self._identity,
                self._executor_workdir,
                classpath,
                dist,
                startup_timeout=self.get_options().nailgun_subprocess_startup_timeout,
                connect_timeout=self.get_options().nailgun_timeout_seconds,
                connect_attempts=self.get_options().nailgun_connect_attempts,
            )
        else:
            return SubprocessExecutor(dist)

    def runjava(
        self,
        classpath,
        main,
        jvm_options=None,
        args=None,
        workunit_name=None,
        workunit_labels=None,
        workunit_log_config=None,
        dist=None,
        force_subprocess=False,
    ):
        """Runs the java main using the given classpath and args.

        If --execution-strategy=subprocess is specified then the java main is run in a freshly spawned
        subprocess, otherwise a persistent nailgun server dedicated to this Task subclass is used to
        speed up amortized run times.

        :API: public
        """
        executor = self.create_java_executor(dist=dist, force_subprocess=force_subprocess)

        # Creating synthetic jar to work around system arg length limit is not necessary
        # when `NailgunExecutor` is used because args are passed through socket, therefore turning off
        # creating synthetic jar if nailgun is used.
        create_synthetic_jar = (
            self.execution_strategy != self.ExecutionStrategy.nailgun or force_subprocess
        )
        try:
            return util.execute_java(
                classpath=classpath,
                main=main,
                jvm_options=jvm_options,
                args=args,
                cwd=get_buildroot(),
                executor=executor,
                workunit_factory=self.context.new_workunit,
                workunit_name=workunit_name,
                workunit_labels=workunit_labels,
                workunit_log_config=workunit_log_config,
                create_synthetic_jar=create_synthetic_jar,
                synthetic_jar_dir=self._executor_workdir,
            )
        except executor.Error as e:
            raise TaskError(e)


# TODO(John Sirois): This just prevents ripple - maybe inline
class NailgunTask(NailgunTaskBase, Task):
    """
    :API: public
    """

    pass


class NailgunKillall(Task):
    """Kill running nailgun servers."""

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--everywhere",
            type=bool,
            help="Kill all nailguns servers launched by pants for all workspaces on the system.",
        )

    def execute(self):
        NailgunProcessGroup().killall(everywhere=self.get_options().everywhere)
