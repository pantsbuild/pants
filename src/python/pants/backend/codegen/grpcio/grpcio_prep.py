# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os

from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder

from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.subsystems.pex_build_util import PexBuilderWrapper
from pants.backend.python.subsystems.python_repos import PythonRepos
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.base.build_environment import get_buildroot
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.address import Address
from pants.subsystem.subsystem import Subsystem
from pants.task.task import Task
from pants.util.dirutil import fast_relpath, safe_concurrent_creation


logger = logging.getLogger(__name__)


class GrpcioPrep(Task):
  class Grpcio(object):
    class Factory(Subsystem):
      options_scope = 'grpcio'

      @classmethod
      def register_options(cls, register):
        super(GrpcioPrep.Grpcio.Factory, cls).register_options(register)

      @classmethod
      def create_requirements(cls, context, workdir, grpcio_version):
        address = Address(spec_path=cls._relative_path(workdir), target_name='grpcio')
        requirements = [
          'grpcio-tools=={}'.format(grpcio_version),
          'grpcio=={}'.format(grpcio_version),
        ]
        context.build_graph.inject_synthetic_target(
          address=address,
          target_type=PythonRequirementLibrary,
          requirements=[PythonRequirement(r) for r in requirements]
        )
        return context.build_graph.get_target(address=address)

      @classmethod
      def _relative_path(cls, workdir):
        if get_buildroot() in workdir:
          return fast_relpath(workdir, get_buildroot())
        return ''

      @classmethod
      def build_grpcio_pex(cls, context, interpreter, pex_path, requirements_lib):
        with safe_concurrent_creation(pex_path) as chroot:
          pex_builder = PexBuilderWrapper(
            PEXBuilder(path=chroot, interpreter=interpreter),
            PythonRepos.global_instance(),
            PythonSetup.global_instance(),
            context.log)
          pex_builder.add_requirement_libs_from(req_libs=[requirements_lib])
          pex_builder.set_entry_point('grpc_tools.protoc')
          pex_builder.freeze()

    def __init__(self, pex_path, interpreter=None):
      self._pex = PEX(pex_path, interpreter=interpreter)

    def run(self, workunit_factory, args, **kwargs):
      cmdline = ' '.join(self._pex.cmdline(args))
      with workunit_factory(cmd=cmdline) as workunit:
        logger.info(args)
        exit_code = self._pex.run(args,
                                  stdout=workunit.output('stdout'),
                                  stderr=workunit.output('stderr'),
                                  with_chroot=False,
                                  blocking=True,
                                  **kwargs)
        logging.info('exit_code: [{}]'.format(exit_code))
        return cmdline, exit_code

  @classmethod
  def register_options(cls, register):
    register(
      '--grpcio-version',
      default='1.17.1',
      help='The version of grpcio to use.')

  @classmethod
  def subsystem_dependencies(cls):
    return super(GrpcioPrep, cls).subsystem_dependencies() + (
      cls.Grpcio.Factory,
      # PythonSetup, PythonRepos are required by dump_requirement_libs.
      PythonSetup,
      PythonRepos
    )

  @classmethod
  def product_types(cls):
    return [cls.Grpcio]

  @property
  def create_target_dirs(self):
    return True

  def execute(self):
    grpcio_version = self.get_options().grpcio_version
    grpcio_requirement_lib = self.Grpcio.Factory.create_requirements(self.context, self.workdir, grpcio_version)

    with self.invalidated(targets=[grpcio_requirement_lib]) as invalidation_check:
      interpreter = PythonInterpreter.get()

      assert len(invalidation_check.all_vts) == 1, (
        'Expected exactly one versioned target found {}: {}'
          .format(len(invalidation_check.all_vts), invalidation_check.all_vts)
      )
      vt = invalidation_check.all_vts[0]
      pex_path = os.path.join(vt.results_dir, 'grpcio.pex')

      if invalidation_check.invalid_vts:
        with self.context.new_workunit(name='create-grpcio-pex', labels=[WorkUnitLabel.PREP]):
          self.Grpcio.Factory.build_grpcio_pex(context=self.context,
                                               interpreter=interpreter,
                                               pex_path=pex_path,
                                               requirements_lib=grpcio_requirement_lib)

      grpcio = self.Grpcio(pex_path, interpreter=interpreter)
      self.context.products.register_data(self.Grpcio, grpcio)
