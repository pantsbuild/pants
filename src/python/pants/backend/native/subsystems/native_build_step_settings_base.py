# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.native.subsystems.utils.mirrored_target_option_mixin import \
  MirroredTargetOptionMixin
from pants.subsystem.subsystem import Subsystem


class NativeBuildStepSettingsBase(Subsystem, MirroredTargetOptionMixin):

  mirrored_option_to_kwarg_map = {
    'fatal_warnings': 'fatal_warnings',
    'ndebug': 'ndebug',
    'glibcxx_use_cxx11_abi': 'glibcxx_use_cxx11_abi',
  }

  @classmethod
  def register_options(cls, register):
    super(NativeBuildStepSettingsBase, cls).register_options(register)

    # TODO: implement compiler_option_sets as an interface to platform/host-specific optimization
    # flags!
    register('--fatal-warnings', type=bool, default=True, fingerprint=True, advanced=True,
             help='The default for the "fatal_warnings" argument for targets of this language.')
    register('--ndebug', type=bool, default=False, fingerprint=True, advanced=True,
             help='The default for the "ndebug" argument for targets of this language.')
    register('--glibcxx-use-cxx11-abi', type=bool, default=False, fingerprint=True, advanced=True,
             help='The default for the "glibcxx_use_cxx11_abi" argument for targets of this language.')

  def get_fatal_warnings_value_for_target(self, target):
    return self.get_target_mirrored_option('fatal_warnings', target)

  def get_ndebug_value_for_target(self, target):
    return self.get_target_mirrored_option('ndebug', target)

  def get_glibcxx_use_cxx11_abi_value_for_target(self, target):
    return self.get_target_mirrored_option('glibcxx_use_cxx11_abi', target)


class CCompileSettings(NativeBuildStepSettingsBase):
  options_scope = 'c-compile-settings'


class CppCompileSettings(NativeBuildStepSettingsBase):
  options_scope = 'cpp-compile-settings'


# TODO: add a fatal_warnings kwarg to NativeArtifact and make a LinkSharedLibrariesSettings subclass
# of NativeBuildStepSettingsBase here! The method should work even though NativeArtifact is not a
# Target.
