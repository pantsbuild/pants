# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import signal

from pex.pex import PEX

from pants.backend.python.python_chroot import PythonChroot
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.tasks.python_task import PythonTask
from pants.base.workunit import WorkUnit


class PythonRun(PythonTask):
  def __init__(self, *args, **kwargs):
    super(PythonRun, self).__init__(*args, **kwargs)

  def execute(self):
    binary = self.require_single_root_target()
    if isinstance(binary, PythonBinary):
      # We can't throw if binary isn't a PythonBinary, because perhaps we were called on a
      # jvm_binary, in which case we have to no-op and let jvm_run do its thing.
      # TODO(benjy): Some more elegant way to coordinate how tasks claim targets.
      interpreter = self.select_interpreter_for_targets(self.context.targets())
      with self.temporary_pex_builder(interpreter=interpreter, pex_info=binary.pexinfo) as builder:
        chroot = PythonChroot(
          targets=[binary],
          builder=builder,
          platforms=binary.platforms,
          interpreter=interpreter,
          conn_timeout=self.conn_timeout)

        chroot.dump()
        builder.freeze()
        pex = PEX(builder.path(), interpreter=interpreter)
        self.context.lock.release()
        with self.context.new_workunit(name='run', labels=[WorkUnit.RUN]):
          po = pex.run(blocking=False)
          try:
            return po.wait()
          except KeyboardInterrupt:
            po.send_signal(signal.SIGINT)
            raise
