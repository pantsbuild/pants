# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import signal

from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder

from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.tasks2.gather_sources import GatherSources
from pants.backend.python.tasks2.resolve_requirements import ResolveRequirements
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.task.task import Task
from pants.util.contextutil import temporary_dir
from pants.util.strutil import safe_shlex_split


class PythonRun(Task):

  @classmethod
  def register_options(cls, register):
    super(PythonRun, cls).register_options(register)
    register('--args', type=list, help='Run with these extra args to main().')

  @classmethod
  def supports_passthru_args(cls):
    return True

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data(PythonInterpreter)
    round_manager.require_data(ResolveRequirements.REQUIREMENTS_PEX)
    round_manager.require_data(GatherSources.PYTHON_SOURCES)

  def execute(self):
    binary = self.require_single_root_target()
    if isinstance(binary, PythonBinary):
      # We can't throw if binary isn't a PythonBinary, because perhaps we were called on a
      # jvm_binary, in which case we have to no-op and let jvm_run do its thing.
      # TODO(benjy): Some more elegant way to coordinate how tasks claim targets.
      interpreter = self.context.products.get_data(PythonInterpreter)

      with temporary_dir() as tmpdir:
        # Create a wrapper pex to "merge" the other pexes into via PEX_PATH.
        builder = PEXBuilder(tmpdir, interpreter, pex_info=binary.pexinfo)
        builder.freeze()

        pexes = [self.context.products.get_data(ResolveRequirements.REQUIREMENTS_PEX),
                 self.context.products.get_data(GatherSources.PYTHON_SOURCES)]

        pex_path = os.pathsep.join([pex.cmdline()[1] for pex in pexes])

        pex = PEX(tmpdir, interpreter)

        self.context.release_lock()
        with self.context.new_workunit(name='run', labels=[WorkUnitLabel.RUN]):
          args = []
          for arg in self.get_options().args:
            args.extend(safe_shlex_split(arg))
          args += self.get_passthru_args()
          po = pex.run(blocking=False, args=args, env={ 'PEX_PATH': pex_path })
          try:
            result = po.wait()
            if result != 0:
              msg = '{interpreter} {entry_point} {args} ... exited non-zero ({code})'.format(
                  interpreter=interpreter.binary,
                  entry_point=binary.entry_point,
                  args=' '.join(args),
                  code=result)
              raise TaskError(msg, exit_code=result)
          except KeyboardInterrupt:
            po.send_signal(signal.SIGINT)
            raise
