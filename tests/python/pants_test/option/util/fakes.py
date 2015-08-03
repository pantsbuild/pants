# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.option.optionable import Optionable
from pants.option.ranked_value import RankedValue


def create_option_values(option_values):
  """Create a fake OptionValueContainer object for testing.

  :param **options: Keyword args representing option values explicitly set via the command line.
  :returns: A fake `OptionValueContainer` encapsulating the given option values.
  """
  class FakeOptionValues(object):
    def __getitem__(self, key):
      return getattr(self, key)

    def get(self, key, default=None):
      if hasattr(self, key):
        return getattr(self, key, default)
      return default

    def __getattr__(self, key):
      value = option_values[key]
      return value.value if isinstance(value, RankedValue) else value

    def get_rank(self, key):
      value = option_values[key]
      return value.rank if isinstance(value, RankedValue) else RankedValue.FLAG

    def is_flagged(self, key):
      return self.get_rank(key) == RankedValue.FLAG
  return FakeOptionValues()


def options_registration_function(defaults):
  """Creates an options registration function suitable for passing to `Optionable.register_options`.

  :param dict defaults: An option value dictionary the registration function will register default
                        option values in.
  :returns: a registration function suitable for passing to `Optionable.register_options`.
  """
  def register(*args, **kwargs):
    default = kwargs.get('default')
    if default is None:
      action = kwargs.get('action')
      if action == 'store_true':
        default = False
      if action == 'append':
        default = []
    for flag_name in args:
      normalized_flag_name = flag_name.lstrip('-').replace('-', '_')
      defaults[normalized_flag_name] = RankedValue(RankedValue.HARDCODED, default)
  return register


def create_option_values_for_optionable(optionable_type, **options):
  """Create a fake OptionValueContainer with appropriate defaults for the given `Optionable` type."

  :param type optionable_type: An :class:`pants.option.optionable.Optionable` subclass.
  :param **options: Keyword args representing option values explicitly set via the command line.
  :returns: A fake `OptionValueContainer`, ie: the value returned from `get_options()`.
  """
  if not issubclass(optionable_type, Optionable):
    raise TypeError('The given `optionable_type` was not a subclass of `Optionable`: {}'
                    .format(optionable_type))

  option_values = {}
  registration_function = options_registration_function(option_values)
  optionable_type.register_options(registration_function)
  option_values.update(**options)
  return create_option_values(option_values)


def create_options(options):
  """Create a fake Options object for testing.

  Note that the returned object only provides access to the provided options values. There is
  no registration mechanism on this object. Code under test shouldn't care about resolving
  cmd-line flags vs. config vs. env vars etc. etc.

  :param dict options: A dict of scope -> (dict of option name -> value).
  :returns: An fake `Options` object encapsulating the given scoped options.
  """
  class FakeOptions(object):
    def for_scope(self, scope):
      return create_option_values(options[scope])

    def for_global_scope(self):
      return self.for_scope('')

    def passthru_args_for_scope(self, scope):
      return []

    def items(self):
      return options.items()

    def registration_args_iter_for_scope(self, scope):
      return []

    def get_fingerprintable_for_scope(self, scope):
      return []

    def __getitem__(self, key):
      return self.for_scope(key)
  return FakeOptions()
