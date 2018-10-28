# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.option.compiler_option_sets_mixin import CompilerOptionSetsMixin
from pants.option.custom_types import dir_option
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method, memoized_property


class CompileSettings(CompilerOptionSetsMixin, Subsystem):

  options_scope = 'compile-settings'

  mirrored_option_to_kwarg_map = {
    'fatal_warnings': 'fatal_warnings',
    'compiler_option_sets': 'compiler_option_sets',
  }

  @classmethod
  def register_options(cls, register):
    super(CompileSettings, cls).register_options(register)

    register('--fatal-warnings', type=bool, default=True, fingerprint=True, advanced=True,
             help='The default for the "fatal_warnings" argument for targets of this language.',
             removal_version='1.14.0.dev2',
             removal_hint='Use compiler options sets instead.')
    register('--hacky-preferred-std-include-dirs', type=list, member_type=dir_option, default=[],
             fingerprint=True, advanced=True, help='???')
    register('--hacky-non-preferred-std-include-dirs', type=list, member_type=dir_option, default=[],
             fingerprint=True, advanced=True, help='???')

  @memoized_method
  def get_fatal_warnings_value_for_target(self, target):
    return self.get_target_mirrored_option('fatal_warnings', target)

  @memoized_property
  def get_hacky_preferred_std_include_dirs(self):
    return self.get_options().hacky_preferred_std_include_dirs

  @memoized_property
  def get_hacky_non_preferred_std_include_dirs(self):
    return self.get_options().hacky_non_preferred_std_include_dirs


class CCompileSettings(Subsystem):
  options_scope = 'c-compile-settings'

  @classmethod
  def register_options(cls, register):
    super(CCompileSettings, cls).register_options(register)

    register('--header-file-extensions', type=list, default=['.h'], fingerprint=True, advanced=True,
             help='???')

  @classmethod
  def subsystem_dependencies(cls):
    return super(CCompileSettings, cls).subsystem_dependencies() + (
      CompileSettings.scoped(cls),
    )

  @memoized_property
  def compile_settings(self):
    return CompileSettings.scoped_instance(self)

  @memoized_property
  def header_file_extensions(self):
    return self.get_options().header_file_extensions


class CppCompileSettings(Subsystem):
  options_scope = 'cpp-compile-settings'

  @classmethod
  def register_options(cls, register):
    super(CppCompileSettings, cls).register_options(register)

    register('--header-file-extensions', type=list, default=['.h', '.hpp'], fingerprint=True,
             advanced=True, help='???')

  @classmethod
  def subsystem_dependencies(cls):
    return super(CppCompileSettings, cls).subsystem_dependencies() + (
      CompileSettings.scoped(cls),
    )

  @memoized_property
  def compile_settings(self):
    return CompileSettings.scoped_instance(self)

  @memoized_property
  def header_file_extensions(self):
    return self.get_options().header_file_extensions


# TODO: add a fatal_warnings kwarg to NativeArtifact and make a LinkSharedLibrariesSettings subclass
# of CompileSettings here! The method should work even though NativeArtifact is not a
# Target.
