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
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.address import Address
from pants.option.custom_types import list_option
from pants.subsystem.subsystem import Subsystem
from pants.task.task import Task
from pants.util.dirutil import fast_relpath, safe_concurrent_creation


class IsortPrep(Task):

  class Isort(object):
    class Factory(Subsystem):
      options_scope = 'isort'

      @classmethod
      def register_options(cls, register):
        super(IsortPrep.Isort.Factory, cls).register_options(register)
        register('--version', default='4.3.4', advanced=True, fingerprint=True,
                 help='The version of isort to use.')
        register('--additional-requirements', default=['setuptools'], type=list_option,
                 advanced=True, fingerprint=True,
                 help='Additional undeclared dependencies of the requested isort version.')

      @classmethod
      def create_requirements(cls, context, workdir):
        options = cls.global_instance().get_options()
        address = Address(spec_path=fast_relpath(workdir, get_buildroot()), target_name='isort')
        requirements = ['isort=={}'.format(options.version)] + options.additional_requirements
        context.build_graph.inject_synthetic_target(
          address=address,
          target_type=PythonRequirementLibrary,
          requirements=[PythonRequirement(r) for r in requirements]
        )
        return context.build_graph.get_target(address=address)

      @classmethod
      def build_isort_pex(cls, context, interpreter, pex_path, requirements_lib):
        with safe_concurrent_creation(pex_path) as chroot:
          pex_builder = PexBuilderWrapper(
            PEXBuilder(path=chroot, interpreter=interpreter),
            PythonRepos.global_instance(),
            PythonSetup.global_instance(),
            context.log)
          pex_builder.add_requirement_libs_from(req_libs=[requirements_lib])
          pex_builder.set_script('isort')
          pex_builder.freeze()

    def __init__(self, pex_path, interpreter=None):
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

  @classmethod
  def subsystem_dependencies(cls):
    return super(IsortPrep, cls).subsystem_dependencies() + (
      cls.Isort.Factory,
      # PythonSetup, PythonRepos are required by dump_requirement_libs.
      PythonSetup,
      PythonRepos
    )

  @classmethod
  def product_types(cls):
    return [cls.Isort]

  @property
  def create_target_dirs(self):
    return True

  def execute(self):
    isort_requirement_lib = self.Isort.Factory.create_requirements(self.context, self.workdir)

    with self.invalidated(targets=[isort_requirement_lib]) as invalidation_check:
      interpreter = PythonInterpreter.get()

      assert len(invalidation_check.all_vts) == 1, (
        'Expected exactly one versioned target found {}: {}'
        .format(len(invalidation_check.all_vts), invalidation_check.all_vts)
      )
      vt = invalidation_check.all_vts[0]
      pex_path = os.path.join(vt.results_dir, 'isort.pex')

      if invalidation_check.invalid_vts:
        with self.context.new_workunit(name='create-isort-pex', labels=[WorkUnitLabel.PREP]):
          self.Isort.Factory.build_isort_pex(context=self.context,
                                             interpreter=interpreter,
                                             pex_path=pex_path,
                                             requirements_lib=isort_requirement_lib)

      isort = self.Isort(pex_path, interpreter=interpreter)
      self.context.products.register_data(self.Isort, isort)
