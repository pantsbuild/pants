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
from pants.backend.python.tasks.pex_build_util import dump_requirement_libs
from pants.base.build_environment import get_buildroot
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.address import Address
from pants.task.task import Task
from pants.util.dirutil import fast_relpath, safe_concurrent_creation


class IsortPrep(Task):

  class Isort(object):
    def __init__(self, pex):
      self._pex = pex

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
    # PythonSetup, PythonRepos are required by dump_requirement_libs.
    return super(IsortPrep, cls).subsystem_dependencies() + (PythonSetup, PythonRepos)

  @classmethod
  def register_options(cls, register):
    super(IsortPrep, cls).register_options(register)
    register('--version', advanced=True, fingerprint=True, default='4.3.4',
             help='The version of isort to use.')

  @classmethod
  def product_types(cls):
    return [cls.Isort]

  @property
  def create_target_dirs(self):
    return True

  def execute(self):
    address = Address(spec_path=fast_relpath(self.workdir, get_buildroot()), target_name='isort')
    self.context.build_graph.inject_synthetic_target(
      address=address,
      target_type=PythonRequirementLibrary,
      requirements=[PythonRequirement(r)
                    for r in 'isort=={}'.format(self.get_options().version), 'setuptools']
    )
    isort_requirements = self.context.build_graph.get_target(address=address)

    with self.invalidated(targets=[isort_requirements]) as invalidation_check:
      interpreter = PythonInterpreter.get()

      assert len(invalidation_check.all_vts) == 1, (
        'Expected exactly one versioned target found {}: {}'
        .format(len(invalidation_check.all_vts), invalidation_check.all_vts)
      )
      vt = invalidation_check.all_vts[0]
      pex_path = os.path.join(vt.results_dir, 'isort.pex')

      if invalidation_check.invalid_vts:
        with self.context.new_workunit(name='create-isort-pex', labels=[WorkUnitLabel.PREP]):
          with safe_concurrent_creation(pex_path) as chroot:
            builder = PEXBuilder(path=chroot, interpreter=interpreter)
            dump_requirement_libs(builder=builder,
                                  interpreter=interpreter,
                                  req_libs=[vt.target],
                                  log=self.context.log)
            builder.set_script('isort')
            builder.freeze()

      isort = PEX(pex_path, interpreter=interpreter)
      self.context.products.register_data(self.Isort, self.Isort(isort))
