# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.native.subsystems.native_build_settings import NativeBuildSettings
from pants.backend.native.subsystems.utils.mirrored_target_option_mixin import \
  MirroredTargetOptionMixin
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property


class NativeBuildStepSettings(Subsystem, MirroredTargetOptionMixin):

  options_scope = 'native-build-step-settings'

  mirrored_option_to_kwarg_map = {
    'fatal_warnings': 'fatal_warnings',
    'compiler_option_sets': 'compiler_option_sets',
  }

  @classmethod
  def subsystem_dependencies(cls):
    return super(NativeBuildStepSettings, cls).subsystem_dependencies() + (
      NativeBuildSettings.scoped(cls),
    )

  @memoized_property
  def _native_build_settings(self):
    return NativeBuildSettings.scoped_instance(self)

  @classmethod
  def register_options(cls, register):
    super(NativeBuildStepSettings, cls).register_options(register)

    # TODO: Deprecate `--fatal-warnings` in a follow-up revision.
    register('--fatal-warnings', type=bool, default=True, fingerprint=True, advanced=True,
             help='The default for the "fatal_warnings" argument for targets of this language.')
    register('--compiler-option-sets-enabled-args', advanced=True, type=dict, fingerprint=True,
             default={}, help='Extra compiler args to use for each enabled option set.')
    register('--compiler-option-sets-disabled-args', advanced=True, type=dict, fingerprint=True,
             default={}, help='Extra compiler args to use for each disabled option set.')

  def get_fatal_warnings_value_for_target(self, target):
    return self.get_target_mirrored_option('fatal_warnings', target)

  def get_merged_compiler_options_for_target(self, target):
    """Merge compiler option sets for a native target into a list of compiler flags.

    :param target: a `NativeLibrary` target that may set a compiler_option_sets argument.
    :returns: compiler_options: a list of compiler flags as individual strings.
    """
    compiler_option_sets = self._native_build_settings.get_target_mirrored_option(
        'compiler_option_sets', target)
    compiler_options = set()

    # Set values for enabled options.
    for opt_set_key in compiler_option_sets:
      val = self.get_options().compiler_option_sets_enabled_args.get(opt_set_key)
      if val:
        compiler_options.update(val)

    # Set values for disabled options.
    for opt_set_key, opt_value in self.get_options().compiler_option_sets_disabled_args.items():
      if not opt_set_key in compiler_option_sets:
        compiler_options.update(opt_value)

    compiler_options = list(compiler_options)
    return compiler_options


class CCompileSettings(Subsystem):
  options_scope = 'c-compile-settings'

  @classmethod
  def subsystem_dependencies(cls):
    return super(CCompileSettings, cls).subsystem_dependencies() + (
      NativeBuildStepSettings.scoped(cls),
    )

  @memoized_property
  def _native_build_step_settings(self):
    return NativeBuildStepSettings.scoped_instance(self)


class CppCompileSettings(Subsystem):
  options_scope = 'cpp-compile-settings'

  @classmethod
  def subsystem_dependencies(cls):
    return super(CppCompileSettings, cls).subsystem_dependencies() + (
      NativeBuildStepSettings.scoped(cls),
    )

  @memoized_property
  def _native_build_step_settings(self):
    return NativeBuildStepSettings.scoped_instance(self)


# TODO: add a fatal_warnings kwarg to NativeArtifact and make a LinkSharedLibrariesSettings subclass
# of NativeBuildStepSettings here! The method should work even though NativeArtifact is not a
# Target.
