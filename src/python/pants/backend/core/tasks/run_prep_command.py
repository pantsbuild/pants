# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
from collections import namedtuple

from pants.backend.core.tasks.task import Task
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel


class RunPrepCommand(Task):

  def execute(self):
    targets = self.context.targets(postorder=True)
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
