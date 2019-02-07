# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import re
from builtins import str
from hashlib import sha1

from future.utils import PY3
from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.platforms import Platform

from pants.backend.native.config.environment import Platform as NativeBackendPlatform
from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.subsystems.pex_build_util import PexBuilderWrapper
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.unpacked_whls import UnpackedWheels
from pants.base.exceptions import TaskError
from pants.base.fingerprint_strategy import DefaultFingerprintHashingMixin, FingerprintStrategy
from pants.task.unpack_remote_sources_base import UnpackRemoteSourcesBase
from pants.util.contextutil import temporary_dir, temporary_file
from pants.util.dirutil import mergetree, safe_concurrent_creation
from pants.util.memo import memoized_classproperty, memoized_method
from pants.util.objects import SubclassesOf
from pants.util.process_handler import subprocess


class UnpackWheelsFingerprintStrategy(DefaultFingerprintHashingMixin, FingerprintStrategy):

  def compute_fingerprint(self, target):
    """UnpackedWheels targets need to be re-unpacked if any of its configuration changes or any of
    the jars they import have changed.
    """
    if isinstance(target, UnpackedWheels):
      hasher = sha1()
      for cache_key in sorted(req.cache_key() for req in target.all_imported_requirements):
        hasher.update(cache_key.encode('utf-8'))
      hasher.update(target.payload.fingerprint().encode('utf-8'))
      return hasher.hexdigest() if PY3 else hasher.hexdigest().decode('utf-8')
    return None


class UnpackWheels(UnpackRemoteSourcesBase):
  """Extract native code from `NativePythonWheel` targets for use by downstream C/C++ sources."""

  source_target_constraint = SubclassesOf(UnpackedWheels)

  def get_fingerprint_strategy(self):
    return UnpackWheelsFingerprintStrategy()

  @classmethod
  def subsystem_dependencies(cls):
    return super(UnpackWheels, cls).subsystem_dependencies() + (
      PexBuilderWrapper.Factory,
      PythonInterpreterCache,
      PythonSetup,
    )

  class _NativeCodeExtractionSetupFailure(Exception): pass

  @staticmethod
  def _exercise_module(pex, expected_module):
    # Ripped from test_resolve_requirements.py.
    with temporary_file(binary_mode=False) as f:
      f.write('import {m}; print({m}.__file__)'.format(m=expected_module))
      f.close()
      proc = pex.run(args=[f.name], blocking=False,
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
      stdout, stderr = proc.communicate()
      return (stdout.decode('utf-8'), stderr.decode('utf-8'))

  @classmethod
  def _get_wheel_dir(cls, pex, module_name):
    """Get the directory of a specific wheel contained within an unpacked pex."""
    stdout_data, stderr_data = cls._exercise_module(pex, module_name)
    if stderr_data != '':
      raise cls._NativeCodeExtractionSetupFailure(
        "Error extracting module '{}' from pex at {}.\nstdout:\n{}\n----\nstderr:\n{}"
        .format(module_name, pex.path, stdout_data, stderr_data))

    module_path = stdout_data.strip()
    wheel_dir = os.path.join(
      module_path[0:module_path.find('{sep}.deps{sep}'.format(sep=os.sep))],
      '.deps',
    )
    if not os.path.isdir(wheel_dir):
      raise cls._NativeCodeExtractionSetupFailure(
        "Wheel dir for module '{}' was not found in path '{}' of pex at '{}'."
        .format(module_name, module_path, pex.path))
    return wheel_dir

  @staticmethod
  def _name_and_platform(whl):
    # The wheel filename is of the format
    # {distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl
    # See https://www.python.org/dev/peps/pep-0425/.
    # We don't care about the python or abi versions because we expect pex to resolve the
    # appropriate versions for the current host.
    parts = os.path.splitext(whl)[0].split('-')
    return '{}-{}'.format(parts[0], parts[1]), parts[-1]

  @memoized_classproperty
  def _current_platform_abbreviation(cls):
    return NativeBackendPlatform.create().resolve_for_enum_variant({
      'darwin': 'macosx',
      'linux': 'linux',
    })

  @classmethod
  def _get_matching_wheel_dir(cls, wheel_dir, module_name):
    wheels = os.listdir(wheel_dir)

    names_and_platforms = {w:cls._name_and_platform(w) for w in wheels}
    for whl_filename, (name, platform) in names_and_platforms.items():
      if cls._current_platform_abbreviation in platform:
        # TODO: this guards against packages which have names that are prefixes of other packages by
        # checking if there is a version number beginning -- is there a more canonical way to do
        # this?
        if re.match(r'^{}\-[0-9]'.format(re.escape(module_name)), name):
          return os.path.join(wheel_dir, whl_filename, module_name)

    raise cls._NativeCodeExtractionSetupFailure(
      "Could not find wheel in dir '{wheel_dir}' matching module name '{module_name}' "
      "for current platform '{pex_current_platform}', when looking for platforms containing the "
      "substring {cur_platform_abbrev}.\n"
      "wheels: {wheels}"
      .format(wheel_dir=wheel_dir,
              module_name=module_name,
              pex_current_platform=Platform.current().platform,
              cur_platform_abbrev=cls._current_platform_abbreviation,
              wheels=wheels))

  def _generate_requirements_pex(self, pex_path, interpreter, requirements):
    if not os.path.exists(pex_path):
      with self.context.new_workunit('extract-native-wheels'):
        with safe_concurrent_creation(pex_path) as chroot:
          pex_builder = PexBuilderWrapper.Factory.create(
            builder=PEXBuilder(path=chroot, interpreter=interpreter),
            log=self.context.log)
          pex_builder.add_resolved_requirements(requirements)
          pex_builder.freeze()
    return PEX(pex_path, interpreter=interpreter)

  @memoized_method
  def _compatible_interpreter(self, unpacked_whls):
    constraints = PythonSetup.global_instance().compatibility_or_constraints(unpacked_whls)
    allowable_interpreters = PythonInterpreterCache.global_instance().setup(filters=constraints)
    return min(allowable_interpreters)

  class NativeCodeExtractionError(TaskError): pass

  def unpack_target(self, unpacked_whls, unpack_dir):
    interpreter = self._compatible_interpreter(unpacked_whls)

    with temporary_dir() as tmp_dir:
      # NB: The pex needs to be in a subdirectory for some reason, and pants task caching ensures it
      # is the only member of this directory, so the dirname doesn't matter.
      pex_path = os.path.join(tmp_dir, 'xxx.pex')
      try:
        pex = self._generate_requirements_pex(pex_path, interpreter,
                                              unpacked_whls.all_imported_requirements)
        wheel_dir = self._get_wheel_dir(pex, unpacked_whls.module_name)
        matching_wheel_dir = self._get_matching_wheel_dir(wheel_dir, unpacked_whls.module_name)
        unpack_filter = self.get_unpack_filter(unpacked_whls)
        # Copy over the module's data files into `unpack_dir`.
        mergetree(matching_wheel_dir, unpack_dir, file_filter=unpack_filter)
      except Exception as e:
        raise self.NativeCodeExtractionError(
          "Error extracting wheel for target {}: {}"
          .format(unpacked_whls, str(e)),
          e)
