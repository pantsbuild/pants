# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.subsystem.subsystem import Subsystem


class NativeCompileSettings(Subsystem):
  """Any settings relevant to a compiler invocation."""

  @classmethod
  def register_options(cls, register):
    super(NativeCompileSettings, cls).register_options(register)

    register('--strict-deps', type=bool, default=True, fingerprint=True, advanced=True,
             help='The default for the "strict_deps" argument for targets of this language.')
    register('--fatal-warnings', type=bool, default=True, fingerprint=True, advanced=True,
             help='The default for the "fatal_warnings" argument for targets of this language.')

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


class CppCompileSettings(NativeCompileSettings):
  options_scope = 'cpp-compile'
