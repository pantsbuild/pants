# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import pkgutil

from pex.pex import PEX

from pants.backend.python.python_chroot import PythonChroot
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.tasks.python_task import PythonTask
from pants.base.exceptions import TaskError
from pants.base.generator import Generator, TemplateData
from pants.base.workunit import WorkUnit
from pants.util.contextutil import temporary_file


class PythonEval(PythonTask):
  class Error(TaskError):
    """A richer failure exception type useful for tests."""

    def __init__(self, *args, **kwargs):
      compiled = kwargs.pop('compiled')
      failed = kwargs.pop('failed')
      super(PythonEval.Error, self).__init__(*args, **kwargs)
      self.compiled = compiled
      self.failed = failed

  _EVAL_TEMPLATE_PATH = os.path.join('templates', 'python_eval', 'eval.py.mustache')

  @staticmethod
  def _is_evalable(target):
    return isinstance(target, (PythonLibrary, PythonBinary))

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
    with self.invalidated(filter(self._is_evalable, targets),
                          topological_order=True) as invalidation_check:
      compiled = self._compile_targets(invalidation_check.invalid_vts)
      return compiled  # Collected and returned for tests

  def _compile_targets(self, invalid_vts):
    with self.context.new_workunit(name='eval-targets', labels=[WorkUnit.MULTITOOL]):
      compiled = []
      failed = []
      for vt in invalid_vts:
        target = vt.target
        return_code = self._compile_target(target)
        if return_code == 0:
          vt.update()  # Ensure partial progress is marked valid
          compiled.append(target)
        else:
          if self.get_options().fail_slow:
            failed.append(target)
          else:
            raise self.Error('Failed to eval {}'.format(target.address.spec),
                             compiled=compiled,
                             failed=[target])

      if failed:
        msg = 'Failed to evaluate {} targets:\n  {}'.format(
            len(failed),
            '\n  '.join(t.address.spec for t in failed))
        raise self.Error(msg, compiled=compiled, failed=failed)

      return compiled

  def _compile_target(self, target):
    with self.context.new_workunit(name=target.address.spec):
      modules = []
      if isinstance(target, PythonBinary):
        source = 'entry_point {}'.format(target.entry_point)
        components = target.entry_point.rsplit(':', 1)
        module = components[0]
        if len(components) == 2:
          function = components[1]
          data = TemplateData(source=source,
                              import_statement='from {} import {}'.format(module, function))
        else:
          data = TemplateData(source=source, import_statement='import {}'.format(module))
        modules.append(data)
      else:
        for path in target.sources_relative_to_source_root():
          if path.endswith('.py'):
            if os.path.basename(path) == '__init__.py':
              module_path = os.path.dirname(path)
            else:
              module_path, _ = os.path.splitext(path)
            source = 'file {}'.format(os.path.join(target.target_base, path))
            module = module_path.replace(os.path.sep, '.')
            data = TemplateData(source=source, import_statement='import {}'.format(module))
            modules.append(data)

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
