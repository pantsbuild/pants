# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import defaultdict

from pants.backend.native.subsystems.native_toolchain import NativeToolchain
from pants.backend.native.targets.native_library import NativeLibrary
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.base.exceptions import IncompatiblePlatformsError
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property
from pants.util.objects import Exactly


class PythonNativeCode(Subsystem):
  """A subsystem which exposes components of the native backend to the python backend."""

  options_scope = 'python-native-code'

  default_native_source_extensions = ['.c', '.cpp', '.cc']

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
      PythonSetup.scoped(cls),
    )

  @memoized_property
  def _native_source_extensions(self):
    return self.get_options().native_source_extensions

  @memoized_property
  def native_toolchain(self):
    return NativeToolchain.scoped_instance(self)

  @memoized_property
  def _python_setup(self):
    return PythonSetup.scoped_instance(self)

  def pydist_has_native_sources(self, target):
    return target.has_sources(extension=tuple(self._native_source_extensions))

  def native_target_has_native_sources(self, target):
    return target.has_sources()

  @memoized_property
  def _native_target_matchers(self):
    return {
      Exactly(PythonDistribution): lambda tgt: self.pydist_has_native_sources,
      Exactly(NativeLibrary): lambda tgt: self.native_target_has_native_sources,
    }

  def _any_targets_have_native_sources(self, targets):
    for tgt in targets:
      for type_constraint, target_predicate in self._native_target_matchers.items():
        if type_constraint.satisfied_by(tgt) and target_predicate(tgt):
          return True
    return False

  def get_targets_by_declared_platform(self, targets):
    """
    Aggregates a dict that maps a platform string to a list of targets that specify the platform.
    If no targets have platforms arguments, return a dict containing platforms inherited from
    the PythonSetup object.

    :param tgts: a list of :class:`Target` objects.
    :returns: a dict mapping a platform string to a list of targets that specify the platform.
    """
    targets_by_platforms = defaultdict(list)

    for tgt in targets:
      for platform in tgt.platforms:
        targets_by_platforms[platform].append(tgt)

    if not targets_by_platforms:
      for platform in self._python_setup.platforms:
        targets_by_platforms[platform] = ['(No target) Platform inherited from either the '
                                          '--platforms option or a pants.ini file.']
    return targets_by_platforms

  _PYTHON_PLATFORM_TARGETS_CONSTRAINT = Exactly(PythonBinary, PythonDistribution)

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

    targets_with_platforms = filter(self._PYTHON_PLATFORM_TARGETS_CONSTRAINT.satisfied_by, targets)
    platforms_with_sources = self.get_targets_by_declared_platform(targets_with_platforms)
    platform_names = platforms_with_sources.keys()

    # There will always be at least 1 platform, because we checked that they have native sources.
    assert(len(platform_names) >= 1)
    if platform_names == ['current']:
      return True

    raise IncompatiblePlatformsError(
      'The target set contains one or more targets that depend on '
      'native code. Please ensure that the platform arguments in all relevant targets and build '
      'options are compatible with the current platform. Found targets for platforms: {}'
      .format(str(platforms_with_sources)))
