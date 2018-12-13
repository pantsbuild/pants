# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

import pex
from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder

from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.subsystems.pex_build_util import PexBuilderWrapper
from pants.base.workunit import WorkUnitLabel
from pants.task.task import Task
from pants.util.dirutil import safe_concurrent_creation


class PythonToolInstance(object):
  def __init__(self, pex_path, interpreter):
    self._pex = PEX(pex_path, interpreter=interpreter)

  def run(self, workunit_factory, args, **kwargs):
    cmdline = ' '.join(self._pex.cmdline(args))
    with workunit_factory(cmd=cmdline) as workunit:
      exit_code = self._pex.run(args,
                                stdout=workunit.output('stdout'),
                                stderr=workunit.output('stderr'),
                                with_chroot=False,
                                blocking=True,
                                **kwargs)
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
      pex_builder.add_resolved_requirements(reqs=reqs)
      pex_builder.set_entry_point(tool_subsystem.get_entry_point())
      pex_builder.freeze()

  def execute(self):
    tool_subsystem = self.tool_subsystem_cls.scoped_instance(self)
    pex_name = tool_subsystem.options_scope
    pex_path = os.path.join(self.workdir, self.fingerprint, '{}.pex'.format(pex_name))

    # TODO(John Sirois): Eliminate setup_interpreter call once pex API is fixed:
    #   https://github.com/pantsbuild/pex/issues/632
    interpreter = pex.vendor.setup_interpreter(PythonInterpreter.get())

    if not os.path.exists(pex_path):
      with self.context.new_workunit(name='create-{}-pex'.format(pex_name),
                                     labels=[WorkUnitLabel.PREP]):
        self._build_tool_pex(tool_subsystem=tool_subsystem,
                             interpreter=interpreter,
                             pex_path=pex_path)

    tool_instance = self.tool_instance_cls(pex_path, interpreter)
    self.context.products.register_data(self.tool_instance_cls, tool_instance)
