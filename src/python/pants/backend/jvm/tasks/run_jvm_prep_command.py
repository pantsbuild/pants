# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.jvm_prep_command import JvmPrepCommand
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.java.distribution.distribution import DistributionLocator
from pants.java.executor import SubprocessExecutor
from pants.task.task import Task


class RunJvmPrepCommandBase(Task):
  """Base class to enable running JVM binaries before executing a goal

  This task is meant to be subclassed, setting the 'goal' variable appropriately.

  output unless the 'compile_classpath_only' field is set to True in the task
  """
  goal = None
  classpath_product_only = False

  @classmethod
  def prepare(cls, options, round_manager):
    super(RunJvmPrepCommandBase, cls).prepare(options, round_manager)
    round_manager.require_data('compile_classpath')
    if not cls.classpath_product_only:
      round_manager.require_data('runtime_classpath')

  @classmethod
  def is_prep(cls, tgt):
    return isinstance(tgt, JvmPrepCommand) and tgt.payload.get_field_value('goal') == cls.goal

  def execute(self):
    if self.goal not in JvmPrepCommand.goals():
      raise  TaskError("Expected goal to be one of {}".format(JvmPrepCommand.goals()))

    targets = self.context.targets(postorder=True,  predicate=self.is_prep)

    compile_classpath = self.context.products.get_data('compile_classpath')
    classpath_products = self.context.products.get_data('runtime_classpath', compile_classpath.copy)

    with self.context.new_workunit(name='jvm_prep_command', labels=[WorkUnitLabel.PREP]) as workunit:
      for target in targets:
        distribution = self.preferred_jvm_distribution(target.platform)
        executor = SubprocessExecutor(distribution)

        mainclass = target.payload.get_field_value('mainclass')
        args = target.payload.get_field_value('args', [])
        target_jvm_options = target.payload.get_field_value('jvm_options', [])
        cp = list(ClasspathUtil.classpath(target.closure(), classpath_products))
        if not cp:
          raise TaskError('target {} has no classpath. (Add dependencies= parameter?'
                          .format(target.address.spec))
        self.context.log.info('Running prep command for {}'.format(target.address.spec))
        returncode = distribution.execute_java(
          executor=executor,
          classpath=cp,
          main=mainclass,
          jvm_options=target_jvm_options,
          args=args,
          workunit_factory=self.context.new_workunit,
          workunit_name='run',
          workunit_labels=[WorkUnitLabel.PREP],
        )

        workunit.set_outcome(WorkUnit.FAILURE if returncode else WorkUnit.SUCCESS)
        if returncode:
          raise TaskError('RunJvmPrepCommand failed to run {}'.format(mainclass))

  def preferred_jvm_distribution(self, platform):
    """Returns a jvm Distribution with a version that should work for all the platforms."""
    if not platform:
      return DistributionLocator.cached()
    return DistributionLocator.cached(minimum_version=platform.target_level)


class RunBinaryJvmPrepCommand(RunJvmPrepCommandBase):
  """Run code from a JVM compiled language before other tasks in the binary goal.

  Register this tasks to run code at the beginning of the binary goal in register.py

   task(name='binary-jvm-prep-command', action=RunBinaryJvmPrepCommand).install('binary', first=True)
  """
  goal = 'binary'


class RunTestJvmPrepCommand(RunJvmPrepCommandBase):
  """Run code from a JVM compiled language before other tasks in the test goal.

  Register this task to run code at the beginning of the test goal in register.py

  task(name='pre-test-jvm-prep-command', action=RunTestJvmPrepCommand).install('test', first=True)
  """
  goal = 'test'


class RunCompileJvmPrepCommand(RunJvmPrepCommandBase):
  """Run code from a JVM compiled language before other tasks in the compile goal.

  Register this tasks to run code at the beginning of the compile goal in register.py

   task(name='compile-jvm-prep-command', action=RunCompileJvmPrepCommand).install('compile', first=True)
  """
  goal = 'compile'
  classpath_product_only = True
