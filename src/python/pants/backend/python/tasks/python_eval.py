# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pex.pex import PEX
from pex.pex_info import PexInfo

from pants.backend.python.python_chroot import PythonChroot
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.tasks.python_task import PythonTask
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.util.contextutil import temporary_file


class PythonEval(PythonTask):
  def execute(self):
    for target in self.context.target_roots:
      self.compile_target(target)

  def compile_target(self, target):
    interpreter = self.select_interpreter_for_targets([target])

    if isinstance(target, PythonBinary):
      pexinfo, platforms = target.pexinfo, target.platforms
    else:
      pexinfo, platforms = PexInfo(), None

    with self.temporary_pex_builder(interpreter=interpreter, pex_info=pexinfo) as builder:
      chroot = PythonChroot(
          context=self.context,
          targets=[target],
          builder=builder,
          platforms=platforms,
          interpreter=interpreter)

      chroot.dump()

      # TODO(John Sirois): XXX switch to collecting files from a target walk instead - '.deps/'
      # knowledge is too coupled to pex internals.
      imports = []
      for path, dirs, files in os.walk(chroot.path()):
        if os.path.realpath(path) == chroot.path():
          for i, d in enumerate(dirs):
            if d == pexinfo.internal_cache:
              del dirs[i]  # don't traverse into the .deps/ dir of the pex.

        relpath = os.path.relpath(path, chroot.path())
        for python_file in filter(lambda f: f.endswith('.py'), files):
          if python_file == '__init__.py':
            imports.append(relpath.replace(os.path.sep, '.'))
          else:
            imports.append(os.path.join(relpath, python_file[:-3]).replace(os.path.sep, '.'))

      if imports:
        with temporary_file() as imports_file:
          imports_file.write('if __name__ == "__main__":\n')
          for module in imports:
            imports_file.write('  import {}\n'.format(module))
          imports_file.write('\n  print("eval success")\n')
          imports_file.close()

          builder.set_executable(imports_file.name, '__pants_python_eval__.py')

          builder.freeze()
          pex = PEX(builder.path(), interpreter=interpreter)
          with self.context.new_workunit(name='eval', labels=[WorkUnit.COMPILER]) as workunit:
            result = pex.run(stdout=workunit.output('stdout'), stderr=workunit.output('stderr'))
            if result != 0:
              raise TaskError('Compile of {} failed.'.format(target.address.spec))
