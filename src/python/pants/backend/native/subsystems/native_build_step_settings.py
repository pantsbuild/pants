# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.native.subsystems.utils.mirrored_target_option_mixin import \
  MirroredTargetOptionMixin
from pants.option.compiler_option_sets_mixin import CompilerOptionSetsMixin
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property
from pants.util.meta import classproperty


class NativeBuildStepSettings(CompilerOptionSetsMixin, MirroredTargetOptionMixin, Subsystem):

  options_scope = 'native-build-step'

  mirrored_option_to_kwarg_map = {
    'compiler_option_sets': 'compiler_option_sets',
  }

  @classmethod
  def register_options(cls, register):
    super(NativeBuildStepSettings, cls).register_options(register)

    register('--compiler-option-sets', advanced=True, default=(), type=list,
             fingerprint=True,
             help='The default for the "compiler_option_sets" argument '
                  'for targets of this language.')

  def get_compiler_option_sets_for_target(self, target):
    return self.get_target_mirrored_option('compiler_option_sets', target)

  @classproperty
  def get_compiler_option_sets_enabled_default_value(cls):
    return {"fatal_warnings": ["-Werror"]}


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
