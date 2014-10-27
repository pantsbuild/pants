# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import subprocess

from pants.backend.core.tasks.task import Task
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.goal.products import MultipleRootedProducts
from pants.util.dirutil import safe_mkdir

class RunPrepCommand(Task):
  def __init__(self, *args, **kwargs):
    super(RunPrepCommand, self).__init__(*args, **kwargs)
    self.confs = self.context.config.getlist('prep', 'confs', default=['default'])

  def execute(self):
    targets = self.context.targets(postorder=True)

    def make_cmdline(target):
      executable = target.payload.get_field_value('prep_command_executable')
      args = target.payload.get_field_value('prep_command_args', [])
      cmdline = [executable]
      cmdline.extend(args)
      return tuple(cmdline)

    def has_prep(target):
      return target.payload.get_field_value('prep_command_executable')

    cmdlines = [make_cmdline(target) for target in targets if has_prep(target)]

    if not cmdlines:
      return

    with self.context.new_workunit(name='prep_command', labels=[WorkUnit.PREP]) as workunit:
      completed_cmdlines = set()
      for cmdline in cmdlines:
        if not cmdline in completed_cmdlines:
          completed_cmdlines.add(cmdline)
          stdout = workunit.output('stdout') if workunit else None
          stderr = workunit.output('stderr') if workunit else None
          try:
            process = subprocess.Popen(cmdline, stdout=stdout, stderr=stderr)
          except OSError as e:
            workunit.set_outcome(WorkUnit.FAILURE)
            raise TaskError("RunPrepCommand failed to execute {cmdline}: {error}".format(
              cmdline=cmdline, error=e))
          process.communicate()
          workunit.set_outcome(WorkUnit.FAILURE if process.returncode else WorkUnit.SUCCESS)
          if process.returncode:
            raise TaskError("RunPrepCommand failed to run {cmdline}".format(cmdline=cmdline))
