# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.subsystem.subsystem import Subsystem


class NativeBuildSettings(Subsystem):
  """Any settings relevant to a compiler and/or linker invocation."""
  options_scope = 'native-build-settings'

  @classmethod
  def register_options(cls, register):
    super(NativeBuildSettings, cls).register_options(register)

    register('--strict-deps', type=bool, default=True, fingerprint=True, advanced=True,
             help='The default for the "strict_deps" argument for targets of this language.')
    # TODO: implement compiler_option_sets as an interface to platform/host-specific optimization
    # flags!
    register('--fatal-warnings', type=bool, default=True, fingerprint=True, advanced=True,
             help='The default for the "fatal_warnings" argument for targets of this language.')

  # TODO: consider coalescing existing methods of mirroring options between a target and a subsystem
  # -- see pants.backend.jvm.subsystems.dependency_context.DependencyContext#defaulted_property()!
  def get_subsystem_target_mirrored_field_value(self, field_name, target):
    """Get the attribute `field_name` from `target` if set, else from this subsystem's options."""
    tgt_setting = getattr(target, field_name)
    if tgt_setting is None:
      return getattr(self.get_options(), field_name)
    return tgt_setting
