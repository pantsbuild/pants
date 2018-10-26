# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.option.compiler_option_sets_mixin import CompilerOptionSetsMixin
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property


class NativeBuildStepSettings(CompilerOptionSetsMixin, Subsystem):

  options_scope = 'native-build-step-settings'

  mirrored_option_to_kwarg_map = {
    'fatal_warnings': 'fatal_warnings',
    'compiler_option_sets': 'compiler_option_sets',
  }

  @classmethod
  def register_options(cls, register):
    super(NativeBuildStepSettings, cls).register_options(register)

    register('--fatal-warnings', type=bool, default=True, fingerprint=True, advanced=True,
             help='The default for the "fatal_warnings" argument for targets of this language.',
             removal_version='1.14.0.dev2',
             removal_hint='Use compiler options sets instead.')

  def get_fatal_warnings_value_for_target(self, target):
    return self.get_target_mirrored_option('fatal_warnings', target)


class CCompileSettings(Subsystem):
  options_scope = 'c-compile-settings'

  @classmethod
  def subsystem_dependencies(cls):
    return super(CCompileSettings, cls).subsystem_dependencies() + (
      NativeBuildStepSettings.scoped(cls),
    )

  @memoized_property
  def native_build_step_settings(self):
    return NativeBuildStepSettings.scoped_instance(self)


class CppCompileSettings(Subsystem):
  options_scope = 'cpp-compile-settings'

  @classmethod
  def subsystem_dependencies(cls):
    return super(CppCompileSettings, cls).subsystem_dependencies() + (
      NativeBuildStepSettings.scoped(cls),
    )

  @memoized_property
  def native_build_step_settings(self):
    return NativeBuildStepSettings.scoped_instance(self)


# TODO: add a fatal_warnings kwarg to NativeArtifact and make a LinkSharedLibrariesSettings subclass
# of NativeBuildStepSettings here! The method should work even though NativeArtifact is not a
# Target.
