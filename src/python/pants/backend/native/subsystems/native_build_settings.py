# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import str

from pants.backend.native.subsystems.utils.mirrored_target_option_mixin import \
  MirroredTargetOptionMixin
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property
from pants.util.objects import enum


class ToolchainVariant(enum('descriptor', ['llvm', 'gnu'])): pass


class NativeBuildSettings(Subsystem, MirroredTargetOptionMixin):
  """Any settings relevant to a compiler and/or linker invocation."""
  options_scope = 'native-build-settings'

  mirrored_option_to_kwarg_map = {
    'strict_deps': 'strict_deps',
  }

  @classmethod
  def register_options(cls, register):
    super(NativeBuildSettings, cls).register_options(register)

    # TODO: rename this so it's clear it is not the same option as JVM strict deps!
    register('--strict-deps', type=bool, default=True, fingerprint=True, advanced=True,
             help="Whether to include only dependencies directly declared in the BUILD file "
                  "for C and C++ targets by default. If this is False, all transitive dependencies "
                  "are used when compiling and linking native code. C and C++ targets may override "
                  "this behavior with the strict_deps keyword argument as well.")

    register('--toolchain-variant', type=str,
             choices=ToolchainVariant.allowed_values,
             default=ToolchainVariant.default_value,
             fingerprint=True, advanced=True,
             help='???')

  def get_strict_deps_value_for_target(self, target):
    return self.get_target_mirrored_option('strict_deps', target)

  @memoized_property
  def toolchain_variant(self):
    return ToolchainVariant.create(self.get_options().toolchain_variant)
