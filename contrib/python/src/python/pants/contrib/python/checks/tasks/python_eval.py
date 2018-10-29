# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import hashlib
import os
import pkgutil
from builtins import open, str

from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.subsystems.python_repos import PythonRepos
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_target import PythonTarget
from pants.backend.python.tasks.pex_build_util import (PexBuilderWrapper, has_python_requirements,
                                                       has_python_sources)
from pants.backend.python.tasks.resolve_requirements_task_base import ResolveRequirementsTaskBase
from pants.base.exceptions import TaskError
from pants.base.generator import Generator, TemplateData
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.task.lint_task_mixin import LintTaskMixin
from pants.util.dirutil import safe_concurrent_creation, safe_mkdir
from pants.util.memo import memoized_property
from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo


class PythonEval(LintTaskMixin, ResolveRequirementsTaskBase):
  class Error(TaskError):
    """A richer failure exception type useful for tests."""

    def __init__(self, *args, **kwargs):
      compiled = kwargs.pop('compiled')
      failed = kwargs.pop('failed')
      super(PythonEval.Error, self).__init__(*args, **kwargs)
      self.compiled = compiled
      self.failed = failed

  _EXEC_NAME = '__pants_executable__'
  _EVAL_TEMPLATE_PATH = os.path.join('templates', 'python_eval', 'eval.py.mustache')

  @classmethod
  def subsystem_dependencies(cls):
    return super(PythonEval, cls).subsystem_dependencies() + (PythonRepos, PythonSetup)

  @classmethod
  def prepare(cls, options, round_manager):
    # We don't need an interpreter selected for all targets in play, so prevent one being selected.
    pass

  @staticmethod
  def _is_evalable(target):
    return isinstance(target, (PythonLibrary, PythonBinary))

  @classmethod
  def register_options(cls, register):
    super(PythonEval, cls).register_options(register)
    register('--fail-slow', type=bool,
             help='Compile all targets and present the full list of errors.')

  def execute(self):
    with self.invalidated(self.get_targets(self._is_evalable),
                          invalidate_dependents=True,
                          topological_order=True) as invalidation_check:
      compiled = self._compile_targets(invalidation_check.invalid_vts)
      return compiled  # Collected and returned for tests
      # TODO: BAD! Find another way to detect task action in tests.

  @memoized_property
  def _interpreter_cache(self):
    return PythonInterpreterCache(PythonSetup.global_instance(),
                                  PythonRepos.global_instance(),
                                  logger=self.context.log.debug)

  def _compile_targets(self, invalid_vts):
    with self.context.new_workunit(name='eval-targets', labels=[WorkUnitLabel.MULTITOOL]):
      compiled = []
      failed = []
      for vt in invalid_vts:
        target = vt.target
        return_code = self._compile_target(vt)
        if return_code == 0:
          vt.update()  # Ensure partial progress is marked valid.
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

  def _compile_target(self, vt):
    """'Compiles' a python target.

    'Compiling' means forming an isolated chroot of its sources and transitive deps and then
    attempting to import each of the target's sources in the case of a python library or else the
    entry point in the case of a python binary.

    For a library with sources lib/core.py and lib/util.py a "compiler" main file would look like:

      if __name__ == '__main__':
        import lib.core
        import lib.util

    For a binary with entry point lib.bin:main the "compiler" main file would look like:

      if __name__ == '__main__':
        from lib.bin import main

    In either case the main file is executed within the target chroot to reveal missing BUILD
    dependencies.
    """
    target = vt.target
    with self.context.new_workunit(name=target.address.spec):
      modules = self._get_modules(target)
      if not modules:
        # Nothing to eval, so a trivial compile success.
        return 0

      interpreter = self._get_interpreter_for_target_closure(target)
      reqs_pex = self._resolve_requirements_for_versioned_target_closure(interpreter, vt)
      srcs_pex = self._source_pex_for_versioned_target_closure(interpreter, vt)

      # Create the executable pex.
      exec_pex_parent = os.path.join(self.workdir, 'executable_pex')
      executable_file_content = self._get_executable_file_content(exec_pex_parent, modules)

      hasher = hashlib.sha1()
      hasher.update(reqs_pex.path().encode('utf-8'))
      hasher.update(srcs_pex.path().encode('utf-8'))
      hasher.update(executable_file_content.encode('utf-8'))
      exec_file_hash = hasher.hexdigest()
      exec_pex_path = os.path.realpath(os.path.join(exec_pex_parent, exec_file_hash))
      if not os.path.isdir(exec_pex_path):
        with safe_concurrent_creation(exec_pex_path) as safe_path:
          # Write the entry point.
          safe_mkdir(safe_path)
          with open(os.path.join(safe_path, '{}.py'.format(self._EXEC_NAME)), 'w') as outfile:
            outfile.write(executable_file_content)
          pex_info = (target.pexinfo if isinstance(target, PythonBinary) else None) or PexInfo()
          # Override any user-specified entry point, under the assumption that the
          # executable_file_content does what the user intends (including, probably, calling that
          # underlying entry point).
          pex_info.entry_point = self._EXEC_NAME
          pex_info.pex_path = ':'.join(pex.path() for pex in (reqs_pex, srcs_pex) if pex)
          builder = PEXBuilder(safe_path, interpreter, pex_info=pex_info)
          builder.freeze()

      pex = PEX(exec_pex_path, interpreter)

      with self.context.new_workunit(name='eval',
                                     labels=[WorkUnitLabel.COMPILER, WorkUnitLabel.RUN,
                                             WorkUnitLabel.TOOL],
                                     cmd=' '.join(pex.cmdline())) as workunit:
        returncode = pex.run(stdout=workunit.output('stdout'), stderr=workunit.output('stderr'))
        workunit.set_outcome(WorkUnit.SUCCESS if returncode == 0 else WorkUnit.FAILURE)
        if returncode != 0:
          self.context.log.error('Failed to eval {}'.format(target.address.spec))
        return returncode

  @staticmethod
  def _get_modules(target):
    modules = []
    if isinstance(target, PythonBinary):
      source = 'entry_point {}'.format(target.entry_point)
      components = target.entry_point.rsplit(':', 1)
      if not all([x.strip() for x in components]):
        raise TaskError('Invalid entry point {} for target {}'.format(
          target.entry_point, target.address.spec))
      module = components[0]
      if len(components) == 2:
        func = components[1]
        data = TemplateData(source=source,
                            import_statement='from {} import {}'.format(module, func))
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
          if module:
            data = TemplateData(source=source, import_statement='import {}'.format(module))
            modules.append(data)
    return modules

  def _get_executable_file_content(self, exec_pex_parent, modules):
    generator = Generator(pkgutil.get_data(__name__, self._EVAL_TEMPLATE_PATH).decode('utf-8'),
                          chroot_parent=exec_pex_parent, modules=modules)
    return generator.render()

  def _get_interpreter_for_target_closure(self, target):
    targets = [t for t in target.closure() if isinstance(t, PythonTarget)]
    return self._interpreter_cache.select_interpreter_for_targets(targets)

  def _resolve_requirements_for_versioned_target_closure(self, interpreter, vt):
    reqs_pex_path = os.path.realpath(os.path.join(self.workdir, str(interpreter.identity),
                                                  vt.cache_key.hash))
    if not os.path.isdir(reqs_pex_path):
      req_libs = [t for t in vt.target.closure() if has_python_requirements(t)]
      with safe_concurrent_creation(reqs_pex_path) as safe_path:
        pex_builder = PexBuilderWrapper(
          PEXBuilder(safe_path, interpreter=interpreter, copy=True),
          PythonRepos.global_instance(),
          PythonSetup.global_instance(),
          self.context.log)
        pex_builder.add_requirement_libs_from(req_libs)
        pex_builder.freeze()
    return PEX(reqs_pex_path, interpreter=interpreter)

  def _source_pex_for_versioned_target_closure(self, interpreter, vt):
    source_pex_path = os.path.realpath(os.path.join(self.workdir, vt.cache_key.hash))
    if not os.path.isdir(source_pex_path):
      with safe_concurrent_creation(source_pex_path) as safe_path:
        self._build_source_pex(interpreter, safe_path, vt.target.closure())
    return PEX(source_pex_path, interpreter=interpreter)

  def _build_source_pex(self, interpreter, path, targets):
    pex_builder = PexBuilderWrapper(
      PEXBuilder(path=path, interpreter=interpreter, copy=True),
      PythonRepos.global_instance(),
      PythonSetup.global_instance(),
      self.context.log)
    for target in targets:
      if has_python_sources(target):
        pex_builder.add_sources_from(target)
    pex_builder.freeze()
