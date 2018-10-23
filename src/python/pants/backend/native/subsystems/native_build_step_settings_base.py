# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.native.subsystems.utils.mirrored_target_option_mixin import \
  MirroredTargetOptionMixin
from pants.subsystem.subsystem import Subsystem


class NativeBuildStepSettingsBase(Subsystem, NativeBuildSettings, MirroredTargetOptionMixin):

  mirrored_option_to_kwarg_map = {
    'fatal_warnings': 'fatal_warnings',
    'compiler_option_sets': 'compiler_option_sets',
  }

  @classmethod
  def register_options(cls, register):
    super(NativeBuildStepSettingsBase, cls).register_options(register)

    register('--fatal-warnings-enabled-args', advanced=True, type=list, fingerprint=True,
             default=list(cls.get_fatal_warnings_enabled_args_default()),
             help='Extra compiler args to use when fatal warnings are enabled.')
    register('--fatal-warnings-disabled-args', advanced=True, type=list, fingerprint=True,
             default=list(cls.get_fatal_warnings_disabled_args_default()),
             help='Extra compiler args to use when fatal warnings are disabled.')
    register('--compiler-option-sets-enabled-args', advanced=True, type=dict, fingerprint=True,
             default={
              'fatal_warnings': list(cls.get_fatal_warnings_enabled_args_default()),
             },
             help='Extra compiler args to use for each enabled option set.')
    register('--compiler-option-sets-disabled-args', advanced=True, type=dict, fingerprint=True,
             default={
              'fatal_warnings': list(cls.get_fatal_warnings_disabled_args_default()),
             },
             help='Extra compiler args to use for each disabled option set.')

  @classmethod
  def get_fatal_warnings_enabled_args_default(cls):
    """Override to set default for this option."""
    return ('-Werror',)

  @classmethod
  def get_fatal_warnings_disabled_args_default(cls):
    """Override to set default for this option."""
    return ()

  def get_merged_compiler_options_for_target(self, target):
    fatal_warnings = self.get_target_mirrored_option('fatal_warnings', target)
    compiler_option_sets = self.get_compiler_option_sets_for_target(target)
    compiler_options = []
    if compiler_option_sets:
      for option_set_key in compiler_option_sets:
        compiler_option_sets.update(
          self.get_options().compiler_option_sets_enabled_args[option_set_key]
        )
        compiler_options = list(compiler_option_sets)
    return compiler_options


class CCompileSettings(NativeBuildStepSettingsBase):
  options_scope = 'c-compile-settings'


class CppCompileSettings(NativeBuildStepSettingsBase):
  options_scope = 'cpp-compile-settings'


# TODO: add a fatal_warnings kwarg to NativeArtifact and make a LinkSharedLibrariesSettings subclass
# of NativeBuildStepSettingsBase here! The method should work even though NativeArtifact is not a
# Target.
