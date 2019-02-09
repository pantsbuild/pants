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
from pants.util.objects import enum, register_enum_option


class ToolchainVariant(enum(['gnu', 'llvm'])): pass


class NativeBuildStep(CompilerOptionSetsMixin, MirroredTargetOptionMixin, Subsystem):
  """Settings which are specific to a target and do not need to be the same for compile and link."""

  options_scope = 'native-build-step'

  mirrored_option_to_kwarg_map = {
    'compiler_option_sets': 'compiler_option_sets',
    'toolchain_variant': 'toolchain_variant'
  }

  @classmethod
  def register_options(cls, register):
    super(NativeBuildStep, cls).register_options(register)

    register('--compiler-option-sets', advanced=True, default=(), type=list,
             fingerprint=True,
             help='The default for the "compiler_option_sets" argument '
                  'for targets of this language.')

    register_enum_option(
      register, ToolchainVariant, '--toolchain-variant', advanced=True,
      help="Whether to use gcc (gnu) or clang (llvm) to compile C and C++. Currently all "
           "linking is done with binutils ld on Linux, and the XCode CLI Tools on MacOS.")

  def get_compiler_option_sets_for_target(self, target):
    return self.get_target_mirrored_option('compiler_option_sets', target)

  def get_toolchain_variant_for_target(self, target):
    return ToolchainVariant.create(self.get_target_mirrored_option('toolchain_variant', target))

  @classproperty
  def get_compiler_option_sets_enabled_default_value(cls):
    return {"fatal_warnings": ["-Werror"]}


class CompileSettingsBase(Subsystem):

  @classmethod
  def subsystem_dependencies(cls):
    return super(CompileSettingsBase, cls).subsystem_dependencies() + (
      NativeBuildStep.scoped(cls),
    )

  @classproperty
  def header_file_extensions_default(cls):
    raise NotImplementedError('header_file_extensions_default() must be overridden!')

  @classmethod
  def register_options(cls, register):
    super(CompileSettingsBase, cls).register_options(register)
    register('--header-file-extensions', advanced=True, default=cls.header_file_extensions_default,
             type=list, fingerprint=True,
             help="The file extensions which should not be provided to the compiler command line.")

  @memoized_property
  def native_build_step(self):
    return NativeBuildStep.scoped_instance(self)

  @memoized_property
  def header_file_extensions(self):
    return self.get_options().header_file_extensions


class CCompileSettings(CompileSettingsBase):
  options_scope = 'c-compile-settings'

  header_file_extensions_default = ['.h']


class CppCompileSettings(CompileSettingsBase):
  options_scope = 'cpp-compile-settings'

  header_file_extensions_default = ['.h', '.hpp', '.hxx', '.tpp']


# TODO: add a fatal_warnings kwarg to NativeArtifact and make a LinkSharedLibrariesSettings subclass
# of NativeBuildStep here! The method should work even though NativeArtifact is not a
# Target.
