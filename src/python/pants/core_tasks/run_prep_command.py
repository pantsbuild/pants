# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
from collections import namedtuple

from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.build_graph.prep_command import PrepCommand
from pants.task.task import Task


class RunPrepCommandBase(Task):
  """Base class to enable running shell commands before executing a goal.

  This task is meant to be subclassed, setting the 'goal' variable appropriately.
  For example, create a subclass and then register it in a plugin to run
  at the beginning of the binary goal in register.py:

  task(name='binary-prep-command', action=RunBinaryPrepCommand).install('binary', first=True)

  :API: public
  """
  goal = None

  @classmethod
  def register_options(cls, register):
    """Register options for this optionable.

    In this case, there are no special options, but we want to use this opportunity to setup
    goal validation in PrepCommand before the build graph is parsed.
    """
    super(RunPrepCommandBase, cls).register_options(register)
    PrepCommand.add_allowed_goal(cls.goal)

  @classmethod
  def runnable_prep_cmd(cls, tgt):
    return isinstance(tgt, PrepCommand) and cls.goal in tgt.goals

  def execute(self):
    if self.goal not in PrepCommand.allowed_goals():
      raise AssertionError('Got goal "{}". Expected goal to be one of {}'.format(
          self.goal, PrepCommand.goals()))

    targets = self.context.targets(postorder=True, predicate=self.runnable_prep_cmd)
    Cmdline = namedtuple('Cmdline', ['cmdline', 'environ'])

    def make_cmdline(target):
      executable = target.payload.get_field_value('prep_command_executable')
      args = target.payload.get_field_value('prep_command_args', [])
      prep_environ = target.payload.get_field_value('prep_environ')
      cmdline = [executable]
      cmdline.extend(args)
      return Cmdline(cmdline=tuple(cmdline), environ=prep_environ)

    def has_prep(target):
      return target.payload.get_field_value('prep_command_executable')

    cmdlines = [make_cmdline(target) for target in targets if has_prep(target)]

    if not cmdlines:
      return

    with self.context.new_workunit(name='prep_command', labels=[WorkUnitLabel.PREP]) as workunit:
      completed_cmdlines = set()
      for item in cmdlines:
        cmdline = item.cmdline
        environ = item.environ
        if not cmdline in completed_cmdlines:
          completed_cmdlines.add(cmdline)
          stderr = workunit.output('stderr') if workunit else None
          try:
            process = subprocess.Popen(cmdline, stdout=subprocess.PIPE, stderr=stderr)
          except OSError as e:
            workunit.set_outcome(WorkUnit.FAILURE)
            raise TaskError('RunPrepCommand failed to execute {cmdline}: {error}'.format(
              cmdline=cmdline, error=e))
          stdout, _ = process.communicate()

          if environ:
            if not process.returncode:
              environment_vars = stdout.split('\0')
              for kvpair in environment_vars:
                var, value = kvpair.split('=', 1)
                os.environ[var] = value
          else:
            if workunit:
              workunit.output('stdout').write(stdout)

          workunit.set_outcome(WorkUnit.FAILURE if process.returncode else WorkUnit.SUCCESS)
          if process.returncode:
            raise TaskError('RunPrepCommand failed to run {cmdline}'.format(cmdline=cmdline))


class RunBinaryPrepCommand(RunPrepCommandBase):
  """Run a shell command before other tasks in the binary goal."""
  goal = 'binary'


class RunTestPrepCommand(RunPrepCommandBase):
  """Run a shell command before other tasks in the test goal."""
  goal = 'test'


class RunCompilePrepCommand(RunPrepCommandBase):
  """Run a shell command before other tasks in the compile goal."""
  goal = 'compile'
