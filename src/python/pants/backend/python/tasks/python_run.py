# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import signal

from pex.pex import PEX

from pants.backend.python.python_chroot import PythonChroot
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.tasks.python_task import PythonTask
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit


class PythonRun(PythonTask):
  def __init__(self, *args, **kwargs):
    super(PythonRun, self).__init__(*args, **kwargs)

  @classmethod
  def register_options(cls, register):
    super(PythonRun, cls).register_options(register)
    register('--args', action='append', help='Run with these extra args to main().')

  @classmethod
  def supports_passthru_args(cls):
    return True

  def execute(self):
    binary = self.require_single_root_target()
    if isinstance(binary, PythonBinary):
      # We can't throw if binary isn't a PythonBinary, because perhaps we were called on a
      # jvm_binary, in which case we have to no-op and let jvm_run do its thing.
      # TODO(benjy): Some more elegant way to coordinate how tasks claim targets.
      interpreter = self.select_interpreter_for_targets(self.context.targets())
      with self.temporary_pex_builder(interpreter=interpreter, pex_info=binary.pexinfo) as builder:
        chroot = PythonChroot(
          context=self.context,
          targets=[binary],
          builder=builder,
          platforms=binary.platforms,
          interpreter=interpreter)

        chroot.dump()
        builder.freeze()
        pex = PEX(builder.path(), interpreter=interpreter)
        self.context.release_lock()
        with self.context.new_workunit(name='run', labels=[WorkUnit.RUN]):
          args = self.get_options().args + self.get_passthru_args()
          po = pex.run(blocking=False, args=args)
          try:
            result = po.wait()
            if result != 0:
              raise TaskError('python {args} ... exited non-zero ({code})' %
                              dict(args=args, code=result),
                              exit_code=result)
          except KeyboardInterrupt:
            po.send_signal(signal.SIGINT)
            raise
