# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import pkgutil

from pex.pex import PEX
from twitter.common.collections import OrderedSet

from pants.backend.python.python_chroot import PythonChroot
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.tasks.python_task import PythonTask
from pants.base.exceptions import TaskError
from pants.base.generator import Generator, TemplateData
from pants.base.workunit import WorkUnit
from pants.util.contextutil import temporary_file


class PythonEval(PythonTask):
  _EVAL_TEMPLATE_PATH = os.path.join('templates', 'python_eval', 'eval.py.mustache')

  @classmethod
  def register_options(cls, register):
    super(PythonEval, cls).register_options(register)
    register('--fail-slow', action='store_true', default=False,
             help='Compile all targets and present the full list of errors.')
    register('--closure', action='store_true', default=False,
             help='Eval all targets in the closure individually instead of just the targets '
                  'specified on the command line.')

  def execute(self):
    targets = self.context.targets() if self.get_options().closure else self.context.target_roots
    with self.invalidated(targets, topological_order=True) as invalidation_check:
      self._compile_targets(invalidation_check.invalid_vts)

  def _compile_targets(self, invalid_vts):
    failures = []
    with self.context.new_workunit(name='eval-targets', labels=[WorkUnit.MULTITOOL]):
      for vts in invalid_vts:
        for target in vts.targets:
          if isinstance(target, (PythonLibrary, PythonBinary)):
            returncode = self._compile_target(target)
            if returncode == 0:
              vts.update()  # Ensure partial progress is marked valid
            else:
              if self.get_options().fail_slow:
                failures.append(target)
              else:
                raise TaskError('Failed to eval {}'.format(target.address.spec))
      if failures:
        msg = 'Failed to evaluate {} targets:\n  {}'.format(
          len(failures),
          '\n  '.join(t.address.spec for t in failures))
        raise TaskError(msg)

  def _compile_target(self, target):
    with self.context.new_workunit(name=target.address.spec):
      modules = []
      if isinstance(target, PythonBinary):
        source = 'entrypoint {}'.format(target.entry_point)
        module = target.entry_point.rsplit(':', 1)[0]
        modules.append(TemplateData(source=source, module=module))
      else:
        for path in target.sources_relative_to_source_root():
          if path.endswith('.py'):
            if os.path.basename(path) == '__init__.py':
              module_path = os.path.dirname(path)
            else:
              module_path, _ = os.path.splitext(path)
            source = 'file {}'.format(os.path.join(target.target_base, path))
            module = module_path.replace(os.path.sep, '.')
            modules.append(TemplateData(source=source, module=module))

      if not modules:
        # Nothing to eval, so a trivial compile success.
        return 0

      interpreter = self.select_interpreter_for_targets([target])

      if isinstance(target, PythonBinary):
        pexinfo, platforms = target.pexinfo, target.platforms
      else:
        pexinfo, platforms = None, None

      with self.temporary_pex_builder(interpreter=interpreter, pex_info=pexinfo) as builder:
        with self.context.new_workunit(name='resolve'):
          chroot = PythonChroot(
              context=self.context,
              targets=[target],
              builder=builder,
              platforms=platforms,
              interpreter=interpreter)

          chroot.dump()

        with temporary_file() as imports_file:
          generator = Generator(pkgutil.get_data(__name__, self._EVAL_TEMPLATE_PATH),
                                chroot=chroot.path(),
                                modules=modules)
          generator.write(imports_file)
          imports_file.close()

          builder.set_executable(imports_file.name, '__pants_python_eval__.py')

          builder.freeze()
          pex = PEX(builder.path(), interpreter=interpreter)

          with self.context.new_workunit(name='eval',
                                         labels=[WorkUnit.COMPILER, WorkUnit.RUN, WorkUnit.TOOL],
                                         cmd=' '.join(pex.cmdline())) as workunit:
            returncode = pex.run(stdout=workunit.output('stdout'), stderr=workunit.output('stderr'))
            workunit.set_outcome(WorkUnit.SUCCESS if returncode == 0 else WorkUnit.FAILURE)
            if returncode != 0:
              self.context.log.error('Failed to eval {}'.format(target.address.spec))
            return returncode
