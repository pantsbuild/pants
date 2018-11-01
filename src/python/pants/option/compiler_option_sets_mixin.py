# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import object

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

  def get_merged_args_for_compiler_option_sets(self, compiler_option_sets):
    compiler_options = set()

    # Set values for enabled options.
    for option_set_key in compiler_option_sets:
      # Fatal warnings option has special treatment for backwards compatibility.
      # This is because previously this has had its own {enabled, disabled}_args
      # options when these were defined in the jvm compile task.
      fatal_warnings = self.get_options().fatal_warnings_enabled_args
      if option_set_key == 'fatal_warnings' and fatal_warnings:
        compiler_options.update(fatal_warnings)
      else:
        val = self.get_options().compiler_option_sets_enabled_args.get(option_set_key, ())
        compiler_options.update(val)

    # Set values for disabled options.
    for option_set, disabled_args in self.get_options().compiler_option_sets_disabled_args.items():
      # Fatal warnings option has special treatment for backwards compatibility.
      disabled_fatal_warn_args = self.get_options().fatal_warnings_disabled_args
      if option_set == 'fatal_warnings' and disabled_fatal_warn_args:
        compiler_options.update(disabled_fatal_warn_args)
      else:
        if not option_set in compiler_option_sets:
          compiler_options.update(disabled_args)

    return list(compiler_options)
