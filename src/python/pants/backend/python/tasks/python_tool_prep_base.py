# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from contextlib import contextmanager

from pex.pex import PEX
from pex.pex_builder import PEXBuilder

from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.subsystems.pex_build_util import PexBuilderWrapper
from pants.base.workunit import WorkUnitLabel
from pants.task.task import Task
from pants.util.dirutil import safe_concurrent_creation
from pants.util.process_handler import subprocess
from pants.util.strutil import safe_shlex_join


class PythonToolInstance(object):
  def __init__(self, pex_path, interpreter):
    self._pex = PEX(pex_path, interpreter=interpreter)

  @property
  def pex(self):
    return self._pex

  def output(self, args, input=None, **kwargs):
    cmdline = safe_shlex_join(self._pex.cmdline(args))
    process = self._pex.run(args,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            with_chroot=False,
                            blocking=False,
                            **kwargs)
    (stdout, stderr) = process.communicate(input=input)
    return (stdout, stderr, process.returncode, cmdline)

  @contextmanager
  def run_with(self, workunit_factory, args, **kwargs):
    cmdline = safe_shlex_join(self._pex.cmdline(args))
    with workunit_factory(cmd=cmdline) as workunit:
      exit_code = self._pex.run(args,
                                stdout=workunit.output('stdout'),
                                stderr=workunit.output('stderr'),
                                with_chroot=False,
                                blocking=True,
                                **kwargs)
      yield cmdline, exit_code, workunit

  def run(self, *args, **kwargs):
    with self.run_with(*args, **kwargs) as (cmdline, exit_code, _):
      return cmdline, exit_code


class PythonToolPrepBase(Task):
  """Base class for tasks that resolve a python tool to be invoked out-of-process."""

  # Subclasses must set to a subclass of `pants.backend.python.subsystems.PythonToolBase`.
  tool_subsystem_cls = None

  # Subclasses must set to a subclass of `PythonToolInstance`.  This is the type of the
  # product produced by this task.  It is distinct from the subsystem type so that multiple
  # instances of the same tool, possibly at different versions, can be resolved by different
  # prep tasks, if necessary.
  tool_instance_cls = None

  @classmethod
  def subsystem_dependencies(cls):
    return super(PythonToolPrepBase, cls).subsystem_dependencies() + (
      cls.tool_subsystem_cls.scoped(cls),
      PexBuilderWrapper.Factory,
      PythonInterpreterCache,
    )

  @classmethod
  def product_types(cls):
    return [cls.tool_instance_cls]

  def _build_tool_pex(self, tool_subsystem, interpreter, pex_path):
    with safe_concurrent_creation(pex_path) as chroot:
      pex_builder = PexBuilderWrapper.Factory.create(
        builder=PEXBuilder(path=chroot, interpreter=interpreter),
        log=self.context.log)
      reqs = [PythonRequirement(r) for r in tool_subsystem.get_requirement_specs()]
      pex_builder.add_resolved_requirements(reqs=reqs, platforms=['current'])
      pex_builder.set_entry_point(tool_subsystem.get_entry_point())
      pex_builder.freeze()

  def execute(self):
    tool_subsystem = self.tool_subsystem_cls.scoped_instance(self)
    pex_name = tool_subsystem.options_scope
    pex_path = os.path.join(self.workdir, self.fingerprint, '{}.pex'.format(pex_name))

    interpreter_cache = PythonInterpreterCache.global_instance()
    interpreter = interpreter_cache.select_interpreter_for_targets([])

    if not os.path.exists(pex_path):
      with self.context.new_workunit(name='create-{}-pex'.format(pex_name),
                                     labels=[WorkUnitLabel.PREP]):
        self._build_tool_pex(tool_subsystem=tool_subsystem,
                             interpreter=interpreter,
                             pex_path=pex_path)

    tool_instance = self.tool_instance_cls(pex_path, interpreter)
    self.context.products.register_data(self.tool_instance_cls, tool_instance)
