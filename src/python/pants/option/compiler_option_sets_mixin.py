# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import object

from pants.util.memo import memoized_property
from pants.util.meta import classproperty


class CompilerOptionSetsMixin(object):
  """A mixin for language-scoped that support compiler option sets."""

  @classmethod
  def register_options(cls, register):
    super(CompilerOptionSetsMixin, cls).register_options(register)
    register('--compiler-option-sets-enabled-args', advanced=True, type=dict, fingerprint=True,
             default=cls.get_compiler_option_sets_enabled_default_value,
             help='Extra compiler args to use for each enabled option set.')
    register('--compiler-option-sets-disabled-args', advanced=True, type=dict, fingerprint=True,
             default=cls.get_compiler_option_sets_disabled_default_value,
             help='Extra compiler args to use for each disabled option set.')

  @classproperty
  def get_fatal_warnings_enabled_args_default(cls):
    """Override to set default for this option."""
    return ()

  @classproperty
  def get_fatal_warnings_disabled_args_default(cls):
    """Override to set default for this option."""
    return ()

  @classproperty
  def get_compiler_option_sets_enabled_default_value(cls):
    """Override to set default for this option."""
    return {}

  @classproperty
  def get_compiler_option_sets_disabled_default_value(cls):
    """Override to set default for this option."""
    return {}

  def get_merged_args_for_compiler_option_sets(self, compiler_option_sets):
    compiler_options = set()

    # Set values for enabled options (ignoring fatal_warnings if it has been handled above).
    for option_set_key in compiler_option_sets:
      val = self.get_options().compiler_option_sets_enabled_args.get(option_set_key, ())
      compiler_options.update(val)

    # Set values for disabled options (ignoring fatal_warnings if it has been handled above).
    for option_set_key, disabled_args in self.get_options().compiler_option_sets_disabled_args.items():
      if not option_set_key in compiler_option_sets:
        compiler_options.update(disabled_args)

    return list(compiler_options)
