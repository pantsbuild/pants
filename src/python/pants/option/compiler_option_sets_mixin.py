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

    register('--fatal-warnings-enabled-args', advanced=True, type=list, fingerprint=True,
             default=cls.get_fatal_warnings_enabled_args_default,
             help='Extra compiler args to use when fatal warnings are enabled.',
             removal_version='1.14.0.dev2',
             removal_hint='Use compiler option sets instead.')
    register('--fatal-warnings-disabled-args', advanced=True, type=list, fingerprint=True,
             default=cls.get_fatal_warnings_disabled_args_default,
             help='Extra compiler args to use when fatal warnings are disabled.',
             removal_version='1.14.0.dev2',
             removal_hint='Use compiler option sets instead.')
    register('--compiler-option-sets-enabled-args', advanced=True, type=dict, fingerprint=True,
             default=cls.get_compiler_option_sets_enabled_default_value,
             help='Extra compiler args to use for each enabled option set.')
    register('--compiler-option-sets-disabled-args', advanced=True, type=dict, fingerprint=True,
             default=cls.get_compiler_option_sets_disabled_default_value,
             help='Extra compiler args to use for each disabled option set.')

  @classproperty
  def get_compiler_option_sets_enabled_default_value(cls):
    """Override to set default for this option."""
    return {}

  @classproperty
  def get_compiler_option_sets_disabled_default_value(cls):
    """Override to set default for this option."""
    return {}

  @classproperty
  def get_fatal_warnings_enabled_args_default(cls):
    """Override to set default for this option."""
    return ()

  @classproperty
  def get_fatal_warnings_disabled_args_default(cls):
    """Override to set default for this option."""
    return ()

  @memoized_property
  def _use_deprecated_fatal_warnings(self):
    """Returns true if fatal warnings should be used from their deprecated location.

    The deprecated location is used only if it is explicitly specified, and no args were explicitly
    specified in the new location. This means that either one location or the other will be used,
    but never both.
    """
    set_in_deprecated_location = not self.get_options().is_default('fatal_warnings_enabled_args') or \
                                 not self.get_options().is_default('fatal_warnings_disabled_args')
    set_enabled_in_new_location = (not self.get_options().is_default('compiler_option_sets_enabled_args') and \
                                   bool(self.get_options().compiler_option_sets_enabled_args.get('fatal_warnings', None)))
    set_disabled_in_new_location = (not self.get_options().is_default('compiler_option_sets_disabled_args') and \
                                   bool(self.get_options().compiler_option_sets_disabled_args.get('fatal_warnings', None)))
    return set_in_deprecated_location and not (set_enabled_in_new_location or set_disabled_in_new_location)

  def get_merged_args_for_compiler_option_sets(self, compiler_option_sets):
    compiler_options = set()

    # Start by setting the (deprecated) magically handled fatal warnings option.
    if self._use_deprecated_fatal_warnings:
      if 'fatal_warnings' in compiler_option_sets:
        compiler_options.update(self.get_options().fatal_warnings_enabled_args)
      else:
        compiler_options.update(self.get_options().fatal_warnings_disabled_args)

    # Set values for enabled options (ignoring fatal_warnings if it has been handled above).
    for option_set_key in compiler_option_sets:
      if option_set_key != 'fatal_warnings' or not self._use_deprecated_fatal_warnings:
        val = self.get_options().compiler_option_sets_enabled_args.get(option_set_key, ())
        compiler_options.update(val)

    # Set values for disabled options (ignoring fatal_warnings if it has been handled above).
    for option_set_key, disabled_args in self.get_options().compiler_option_sets_disabled_args.items():
      if not option_set_key in compiler_option_sets:
        if option_set_key != 'fatal_warnings' or not self._use_deprecated_fatal_warnings:
          compiler_options.update(disabled_args)

    return list(compiler_options)
