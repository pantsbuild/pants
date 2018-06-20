# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.subsystem.subsystem import Subsystem


class NativeCompileSettings(Subsystem):
  """Any settings relevant to a compiler invocation."""

  # NB: These seed the --header-file-extensions and --source-file-extensions options for the
  # class. C/C++ source files *must* have one of the extensions specified in their subsystem's
  # header or source file extensions options, or we throw an error. This is done because we want to
  # be able to differentiate headers and sources, but now that I think about it, that might not be
  # necessary.
  default_header_file_extensions = None
  default_source_file_extensions = None

  @classmethod
  def register_options(cls, register):
    super(NativeCompileSettings, cls).register_options(register)

    register('--strict-deps', type=bool, default=True, fingerprint=True, advanced=True,
             help='The default for the "strict_deps" argument for targets of this language.')
    register('--fatal-warnings', type=bool, default=True, fingerprint=True, advanced=True,
             help='The default for the "fatal_warnings" argument for targets of this language.')

    # TODO: make a list of file extension option type?
    register('--header-file-extensions', type=list, default=cls.default_header_file_extensions,
             fingerprint=True, advanced=True,
             help='The allowed extensions for header files, as a list of strings.')
    register('--source-file-extensions', type=list, default=cls.default_source_file_extensions,
             fingerprint=True, advanced=True,
             help='The allowed extensions for source files, as a list of strings.')

  # FIXME: use some more formal method of mirroring options between a target and a subsystem -- see
  # pants.backend.jvm.subsystems.dependency_context.DependencyContext#defaulted_property()!
  def get_subsystem_target_mirrored_field_value(self, field_name, target):
    """Get the attribute `field_name` from `target` if set, else from this subsystem's options."""
    tgt_setting = getattr(target, field_name)
    if tgt_setting is None:
      return getattr(self.get_options(), field_name)
    return tgt_setting


class CCompileSettings(NativeCompileSettings):
  options_scope = 'c-compile'

  default_header_file_extensions = ['.h']
  default_source_file_extensions = ['.c']


class CppCompileSettings(NativeCompileSettings):
  options_scope = 'cpp-compile'

  default_header_file_extensions = ['.h', '.hpp', '.tpp']
  default_source_file_extensions = ['.cpp', '.cxx', '.cc']
