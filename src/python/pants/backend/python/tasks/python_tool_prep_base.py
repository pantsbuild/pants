# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder

from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.subsystems.python_repos import PythonRepos
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.tasks.pex_build_util import PexBuilderWrapper
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.address import Address
from pants.task.task import Task
from pants.util.dirutil import fast_relpath, safe_concurrent_creation


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
      PythonSetup,
      PythonRepos,
    )

  @classmethod
  def product_types(cls):
    return [cls.tool_instance_cls]

  @property
  def create_target_dirs(self):
    return True

  def _tool_subsystem(self):
    return self.tool_subsystem_cls.scoped_instance(self)

  def _create_requirements(self, context, workdir):
    tool_subsystem = self._tool_subsystem()
    address = Address(spec_path=fast_relpath(workdir, get_buildroot()),
                      target_name=tool_subsystem.options_scope)
    context.build_graph.inject_synthetic_target(
      address=address,
      target_type=PythonRequirementLibrary,
      requirements=[PythonRequirement(r) for r in tool_subsystem.get_requirement_specs()]
    )
    return context.build_graph.get_target(address=address)

  def _build_tool_pex(self, context, interpreter, pex_path, requirements_lib):
    with safe_concurrent_creation(pex_path) as chroot:
      pex_builder = PexBuilderWrapper(
        PEXBuilder(path=chroot, interpreter=interpreter),
        PythonRepos.global_instance(),
        PythonSetup.global_instance(),
        context.log)
      pex_builder.add_requirement_libs_from(req_libs=[requirements_lib])
      pex_builder.set_entry_point(self._tool_subsystem().get_entry_point())
      pex_builder.freeze()

  def execute(self):
    tool_req_lib = self._create_requirements(self.context, self.workdir)

    with self.invalidated(targets=[tool_req_lib]) as invalidation_check:
      pex_name = self._tool_subsystem().options_scope
      interpreter = PythonInterpreter.get()
      if len(invalidation_check.all_vts) != 1:
        raise TaskError('Expected exactly one versioned target found {}: {}'.format(
          len(invalidation_check.all_vts), invalidation_check.all_vts))
      vt = invalidation_check.all_vts[0]
      pex_path = os.path.join(vt.results_dir, '{}.pex'.format(pex_name))

      if invalidation_check.invalid_vts:
        with self.context.new_workunit(name='create-{}-pex'.format(pex_name),
                                       labels=[WorkUnitLabel.PREP]):
          self._build_tool_pex(context=self.context,
                               interpreter=interpreter,
                               pex_path=pex_path,
                               requirements_lib=tool_req_lib)

      tool_instance = self.tool_instance_cls(pex_path, interpreter)
      self.context.products.register_data(self.tool_instance_cls, tool_instance)
