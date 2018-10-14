# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.native.subsystems.utils.mirrored_target_option_mixin import \
  MirroredTargetOptionMixin
from pants.subsystem.subsystem import Subsystem


class NativeBuildSettings(Subsystem, MirroredTargetOptionMixin):
  """Any settings relevant to a compiler and/or linker invocation."""
  options_scope = 'native-build-settings'

  mirrored_option_to_kwarg_map = {
    'strict_deps': 'strict_deps',
  }

  @classmethod
  def register_options(cls, register):
    super(NativeBuildSettings, cls).register_options(register)

    register('--strict-deps', type=bool, default=True, fingerprint=True, advanced=True,
             help='The default for the "strict_deps" argument for targets of this language.')

  def get_strict_deps_value_for_target(self, target):
    return self.get_target_mirrored_option('strict_deps', target)
