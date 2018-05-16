# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import signal

from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.tasks.python_execution_task_base import PythonExecutionTaskBase
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.util.strutil import safe_shlex_split


class PythonRun(PythonExecutionTaskBase):
  """Run a Python executable."""

  @classmethod
  def register_options(cls, register):
    super(PythonRun, cls).register_options(register)
    register('--args', type=list, help='Run with these extra args to main().')

  @classmethod
  def supports_passthru_args(cls):
    return True

  def execute(self):
    binary = self.require_single_root_target()
    if isinstance(binary, PythonBinary):
      # We can't throw if binary isn't a PythonBinary, because perhaps we were called on a
      # jvm_binary, in which case we have to no-op and let jvm_run do its thing.
      # TODO(benjy): Use MutexTask to coordinate this.

      pex = self.create_pex(binary.pexinfo)
      args = []
      for arg in self.get_options().args:
        args.extend(safe_shlex_split(arg))
      args += self.get_passthru_args()

      self.context.release_lock()
      with self.context.new_workunit(name='run',
                                     cmd=pex.cmdline(args),
                                     labels=[WorkUnitLabel.TOOL, WorkUnitLabel.RUN]):
        po = pex.run(blocking=False, args=args, env=os.environ.copy())
        try:
          result = po.wait()
          if result != 0:
            msg = '{interpreter} {entry_point} {args} ... exited non-zero ({code})'.format(
                interpreter=pex.interpreter.binary,
                entry_point=binary.entry_point,
                args=' '.join(args),
                code=result)
            raise TaskError(msg, exit_code=result)
        except KeyboardInterrupt:
          po.send_signal(signal.SIGINT)
          raise
