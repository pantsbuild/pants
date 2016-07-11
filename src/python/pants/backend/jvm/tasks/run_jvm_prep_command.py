# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.targets.jvm_prep_command import JvmPrepCommand
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.java.executor import SubprocessExecutor
from pants.task.task import Task


class RunJvmPrepCommandBase(Task):
  """Base class to enable running JVM binaries before executing a goal.

  This command will use the 'runtime_classpath' product and compile dependent JVM code
  unless the 'classpath_product_only' field on the task subclass is set to True.
  Setting `classpath_product_only=True` is useful for running commands before the compile goal
  completes.

  This task is meant to be subclassed, setting the 'goal' variable appropriately.
  For example, create a subclass and then register it in a plugin to run
  at the beginning of the binary goal in register.py:

  task(name='binary-jvm-prep-command', action=RunBinaryJvmPrepCommand).install('binary', first=True)

  :API: public
  """
  goal = None
  classpath_product_only = False

  def __init__(self, context, workdir):
    super(RunJvmPrepCommandBase, self).__init__(context, workdir)
    JvmPrepCommand.add_goal(self.goal)

  @classmethod
  def register_options(cls, register):
    """Register options for this optionable.

    In this case, there are no special options, but we want to use this opportunity to setup
    goal validation in JvmPrepCommand before the build graph is parsed.
    """
    super(RunJvmPrepCommandBase, cls).register_options(register)
    JvmPrepCommand.add_goal(cls.goal)

  @classmethod
  def prepare(cls, options, round_manager):
    """
    :API: public
    """
    super(RunJvmPrepCommandBase, cls).prepare(options, round_manager)
    round_manager.require_data('compile_classpath')
    if not cls.classpath_product_only:
      round_manager.require_data('runtime_classpath')

  @classmethod
  def runnable_prep_cmd(cls, tgt):
    return isinstance(tgt, JvmPrepCommand) and tgt.payload.get_field_value('goal') == cls.goal

  def execute(self):
    if self.goal not in JvmPrepCommand.goals():
      raise  AssertionError('Got goal "{}". Expected goal to be one of {}'.format(
          self.goal, JvmPrepCommand.goals()))

    targets = self.context.targets(postorder=True,  predicate=self.runnable_prep_cmd)

    compile_classpath = self.context.products.get_data('compile_classpath')
    classpath_products = self.context.products.get_data('runtime_classpath', compile_classpath.copy)

    with self.context.new_workunit(name='jvm_prep_command', labels=[WorkUnitLabel.PREP]) as workunit:
      for target in targets:
        distribution = JvmPlatform.preferred_jvm_distribution([target.platform])
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


class RunBinaryJvmPrepCommand(RunJvmPrepCommandBase):
  """Run code from a JVM compiled language before other tasks in the binary goal."""
  goal = 'binary'


class RunTestJvmPrepCommand(RunJvmPrepCommandBase):
  """Run code from a JVM compiled language before other tasks in the test goal."""
  goal = 'test'


class RunCompileJvmPrepCommand(RunJvmPrepCommandBase):
  """Run code from a JVM compiled language before other tasks in the compile goal."""
  goal = 'compile'
  classpath_product_only = True
