# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import str

from pants.backend.native.subsystems.native_toolchain import NativeToolchain
from pants.backend.native.targets.native_library import NativeLibrary
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.subsystems import pex_build_util
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.base.exceptions import IncompatiblePlatformsError
from pants.binaries.executable_pex_tool import ExecutablePexTool
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property
from pants.util.objects import SubclassesOf


class PythonNativeCode(Subsystem):
  """A subsystem which exposes components of the native backend to the python backend."""

  options_scope = 'python-native-code'

  default_native_source_extensions = ['.c', '.cpp', '.cc']

  class PythonNativeCodeError(Exception): pass

  @classmethod
  def register_options(cls, register):
    super(PythonNativeCode, cls).register_options(register)

    register('--native-source-extensions', type=list, default=cls.default_native_source_extensions,
             fingerprint=True, advanced=True,
             help='The extensions recognized for native source files in `python_dist()` sources.')

  @classmethod
  def subsystem_dependencies(cls):
    return super(PythonNativeCode, cls).subsystem_dependencies() + (
      NativeToolchain.scoped(cls),
      PythonSetup,
    )

  @memoized_property
  def _native_source_extensions(self):
    return self.get_options().native_source_extensions

  @memoized_property
  def native_toolchain(self):
    return NativeToolchain.scoped_instance(self)

  @memoized_property
  def _python_setup(self):
    return PythonSetup.global_instance()

  def pydist_has_native_sources(self, target):
    return target.has_sources(extension=tuple(self._native_source_extensions))

  @memoized_property
  def _native_target_matchers(self):
    return {
      SubclassesOf(PythonDistribution): self.pydist_has_native_sources,
      SubclassesOf(NativeLibrary): NativeLibrary.produces_ctypes_native_library,
    }

  def _any_targets_have_native_sources(self, targets):
    # TODO(#5949): convert this to checking if the closure of python requirements has any
    # platform-specific packages (maybe find the platforms there too?).
    for tgt in targets:
      for type_constraint, target_predicate in self._native_target_matchers.items():
        if type_constraint.satisfied_by(tgt) and target_predicate(tgt):
          return True
    return False

  def _get_targets_by_declared_platform_with_placeholders(self, targets_by_platform):
    """
    Aggregates a dict that maps a platform string to a list of targets that specify the platform.
    If no targets have platforms arguments, return a dict containing platforms inherited from
    the PythonSetup object.

    :param tgts: a list of :class:`Target` objects.
    :returns: a dict mapping a platform string to a list of targets that specify the platform.
    """

    if not targets_by_platform:
      for platform in self._python_setup.platforms:
        targets_by_platform[platform] = ['(No target) Platform inherited from either the '
                                          '--platforms option or a pants.ini file.']
    return targets_by_platform

  def check_build_for_current_platform_only(self, targets):
    """
    Performs a check of whether the current target closure has native sources and if so, ensures
    that Pants is only targeting the current platform.

    :param tgts: a list of :class:`Target` objects.
    :return: a boolean value indicating whether the current target closure has native sources.
    :raises: :class:`pants.base.exceptions.IncompatiblePlatformsError`
    """
    if not self._any_targets_have_native_sources(targets):
      return False

    targets_by_platform = pex_build_util.targets_by_platform(targets, self._python_setup)
    platforms_with_sources = self._get_targets_by_declared_platform_with_placeholders(targets_by_platform)
    platform_names = list(platforms_with_sources.keys())

    if len(platform_names) < 1:
      raise self.PythonNativeCodeError(
        "Error: there should be at least one platform in the target closure, because "
        "we checked that there are native sources.")

    if platform_names == ['current']:
      return True

    raise IncompatiblePlatformsError(
      'The target set contains one or more targets that depend on '
      'native code. Please ensure that the platform arguments in all relevant targets and build '
      'options are compatible with the current platform. Found targets for platforms: {}'
      .format(str(platforms_with_sources)))


class BuildSetupRequiresPex(ExecutablePexTool):
  options_scope = 'build-setup-requires-pex'

  @classmethod
  def register_options(cls, register):
    super(BuildSetupRequiresPex, cls).register_options(register)
    register('--setuptools-version', advanced=True, fingerprint=True, default='40.6.3',
             help='The setuptools version to use when executing `setup.py` scripts.')
    register('--wheel-version', advanced=True, fingerprint=True, default='0.32.3',
             help='The wheel version to use when executing `setup.py` scripts.')

  @property
  def base_requirements(self):
    return [
      PythonRequirement('setuptools=={}'.format(self.get_options().setuptools_version)),
      PythonRequirement('wheel=={}'.format(self.get_options().wheel_version)),
    ]
