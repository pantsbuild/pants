# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import re
from builtins import str

from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.platforms import Platform

from pants.backend.native.targets.native_python_wheel import NativePythonWheel
from pants.backend.native.tasks.native_external_library_fetch import NativeExternalLibraryFiles
from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.subsystems.pex_build_util import PexBuilderWrapper
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.base.exceptions import TaskError
from pants.goal.products import UnionProducts
from pants.task.task import Task
from pants.util.contextutil import temporary_file
from pants.util.dirutil import safe_concurrent_creation
from pants.util.process_handler import subprocess


class ExtractNativePythonWheels(Task):

  @classmethod
  def product_types(cls):
    return [NativeExternalLibraryFiles]

  @property
  def cache_target_dirs(self):
    return True

  @classmethod
  def subsystem_dependencies(cls):
    return super(ExtractNativePythonWheels, cls).subsystem_dependencies() + (
      PexBuilderWrapper.Factory,
      PythonInterpreterCache,
      PythonSetup,
    )

  @property
  def _interpreter_cache(self):
    return PythonInterpreterCache.global_instance()

  @staticmethod
  def _exercise_module(pex, expected_module):
    # Ripped from test_resolve_requirements.py in upstream pants.
    with temporary_file(binary_mode=False) as f:
      f.write('import {m}; print({m}.__file__)'.format(m=expected_module))
      f.close()
      proc = pex.run(args=[f.name], blocking=False,
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
      stdout, stderr = proc.communicate()
      return (stdout.decode('utf-8'), stderr.decode('utf-8'))

  @classmethod
  def _get_wheel_dir(cls, pex, module_name):
    stdout_data, stderr_data = cls._exercise_module(pex, module_name)
    assert(stderr_data == '')
    path = stdout_data.strip()
    wheel_dir = os.path.join(path[0:path.find('{sep}.deps{sep}'.format(sep=os.sep))], '.deps')
    assert(os.path.isdir(wheel_dir))
    return wheel_dir

  @staticmethod
  def _name_and_platform(whl):
    # The wheel filename is of the format
    # {distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl
    # See https://www.python.org/dev/peps/pep-0425/.
    # We don't care about the python or abi versions (they depend on what we're currently
    # running on), we just want to make sure we have all the platforms we expect.
    parts = os.path.splitext(whl)[0].split('-')
    return '{}-{}'.format(parts[0], parts[1]), parts[-1]

  @classmethod
  def _get_matching_wheel(cls, wheel_dir, wheels, module_name):
    names_and_platforms = {w:cls._name_and_platform(w) for w in wheels}
    for whl_filename, (name, platform) in names_and_platforms.items():
      cur_platform_abbrev = re.sub(r'_.*', '', Platform.current().platform)
      if platform.startswith(cur_platform_abbrev):
        if name.startswith('{}-'.format(module_name)):
          return os.path.join(wheel_dir, whl_filename, module_name)
    raise Exception("couldn't find anything in names_and_platforms: {}".format(names_and_platforms))

  def _generate_requirements_pex(self, pex_path, interpreter, requirement_target):
    if not os.path.exists(pex_path):
      with self.context.new_workunit('extract-native-wheels'):
        with safe_concurrent_creation(pex_path) as chroot:
          pex_builder = PexBuilderWrapper.Factory.create(
            builder=PEXBuilder(path=chroot, interpreter=interpreter),
            log=self.context.log)
          pex_builder.add_resolved_requirements(requirement_target.requirements)
          pex_builder.freeze()
    return PEX(pex_path, interpreter=interpreter)

  class NativeCodeExtractionError(TaskError): pass

  def execute(self):
    external_lib_files_product = UnionProducts()

    native_wheel_wrappers = self.get_targets(lambda t: isinstance(t, NativePythonWheel))
    with self.invalidated(native_wheel_wrappers, invalidate_dependents=True) as invalidation_check:
      for vt in invalidation_check.all_vts:
        wheel_wrapper = vt.target
        requirement_target = wheel_wrapper.requirement_target

        interpreter = min(self._interpreter_cache.setup(
          filters=PythonSetup.global_instance().interpreter_constraints))

        pex_path = os.path.join(
          vt.results_dir,
          'extract-from-wheel',
          requirement_target.transitive_invalidation_hash(),
          str(interpreter.identity),
        )
        pex = self._generate_requirements_pex(pex_path, interpreter, requirement_target)

        wheel_dir = self._get_wheel_dir(pex, wheel_wrapper.module_name)
        wheels = os.listdir(wheel_dir)
        if len(wheels) == 0:
          raise self.NativeCodeExtractionError('no wheels found in dir {} for target {}!'
                                               .format(wheel_dir, wheel_wrapper))
        matching_wheel = self._get_matching_wheel(wheel_dir, wheels, wheel_wrapper.module_name)

        include_dir = os.path.join(matching_wheel, wheel_wrapper.include_relpath)
        if not os.path.isdir(include_dir):
          raise self.NativeCodeExtractionError('include dir {} not found for target {}!'
                                               .format(include_dir, wheel_wrapper))
        lib_dir = os.path.join(matching_wheel, wheel_wrapper.lib_relpath)
        if not os.path.isdir(lib_dir):
          raise self.NativeCodeExtractionError('lib dir {} not found for target {}!'
                                               .format(lib_dir, wheel_wrapper))
        wrapper_files_product = NativeExternalLibraryFiles(
          include_dir=include_dir,
          lib_dir=lib_dir,
          lib_names=tuple(wheel_wrapper.native_lib_names),
        )
        external_lib_files_product.add_for_target(wheel_wrapper, [wrapper_files_product])

    self.context.products.register_data(NativeExternalLibraryFiles, external_lib_files_product)
