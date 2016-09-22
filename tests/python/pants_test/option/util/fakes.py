# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import defaultdict

from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.global_options import GlobalOptionsRegistrar
from pants.option.optionable import Optionable
from pants.option.parser_hierarchy import enclosing_scope
from pants.option.ranked_value import RankedValue


class _FakeOptionValues(object):
  def __init__(self, option_values):
    self._option_values = option_values

  def __getitem__(self, key):
    return getattr(self, key)

  def get(self, key, default=None):
    if hasattr(self, key):
      return getattr(self, key, default)
    return default

  def __getattr__(self, key):
    try:
      value = self._option_values[key]
    except KeyError:
      # Instead of letting KeyError raise here, re-raise an AttributeError to not break getattr().
      raise AttributeError(key)
    return value.value if isinstance(value, RankedValue) else value

  def get_rank(self, key):
    value = self._option_values[key]
    return value.rank if isinstance(value, RankedValue) else RankedValue.FLAG

  def is_flagged(self, key):
    return self.get_rank(key) == RankedValue.FLAG

  def is_default(self, key):
    return self.get_rank(key) in (RankedValue.NONE, RankedValue.HARDCODED)


def create_option_values(option_values):
  """Create a fake OptionValueContainer object for testing.

  :param **options: Keyword args representing option values explicitly set via the command line.
  :returns: A fake `OptionValueContainer` encapsulating the given option values.
  """
  return _FakeOptionValues(option_values)


def _options_registration_function(defaults):
  def register(*args, **kwargs):
    default = kwargs.get('default')
    if default is None:
      if kwargs.get('type') == bool:
        default = False
      if kwargs.get('type') == list:
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
  registration_function = _options_registration_function(option_values)
  optionable_type.register_options(registration_function)
  option_values.update(**options)
  return create_option_values(option_values)


def create_options(options, passthru_args=None):
  """Create a fake Options object for testing.

  Note that the returned object only provides access to the provided options values. There is
  no registration mechanism on this object. Code under test shouldn't care about resolving
  cmd-line flags vs. config vs. env vars etc. etc.

  :param dict options: A dict of scope -> (dict of option name -> value).
  :returns: An fake `Options` object encapsulating the given scoped options.
  """
  class FakeOptions(object):
    def for_scope(self, scope):
      scoped_options = options[scope]
      # TODO(John Sirois): Some users pass in A dict of scope -> _FakeOptionValues instead of a
      # dict of scope -> (dict of option name -> value).  Clean up these usages and kill this
      # accomodation.
      if isinstance(scoped_options, _FakeOptionValues):
        return scoped_options
      else:
        return create_option_values(scoped_options)

    def for_global_scope(self):
      return self.for_scope('')

    def passthru_args_for_scope(self, scope):
      return passthru_args or []

    def items(self):
      return options.items()

    @property
    def scope_to_flags(self):
      return {}

    def get_fingerprintable_for_scope(self, scope):
      return []

    def __getitem__(self, key):
      return self.for_scope(key)
  return FakeOptions()


def create_options_for_optionables(optionables, extra_scopes=None, options=None):
  """Create a fake Options object for testing with appropriate defaults for the given optionables.

  Any scoped `options` provided will override defaults, behaving as-if set on the command line.

  :param iterable optionables: A series of `Optionable` types to register default options for.
  :param iterable extra_scopes: An optional series of extra known scopes in play.
  :param dict options: A dict of scope -> (dict of option name -> value) representing option values
                       explicitly set via the command line.
  :returns: A fake `Options` object with defaults populated for the given `optionables` and any
            explicitly set `options` overlayed.
  """
  all_options = defaultdict(dict)
  bootstrap_option_values = None

  def complete_scopes(scopes):
    """Return all enclosing scopes.

    This is similar to what `complete_scopes` does in `pants.option.options.Options` without
    creating `ScopeInfo`s.
    """
    completed_scopes = set(scopes)
    for scope in scopes:
      while scope != '':
        if scope not in completed_scopes:
          completed_scopes.add(scope)
        scope = enclosing_scope(scope)
    return completed_scopes

  def register_func(on_scope):
    scoped_options = all_options[on_scope]
    register = _options_registration_function(scoped_options)
    register.bootstrap = bootstrap_option_values
    register.scope = on_scope
    return register

  # TODO: This sequence is a bit repetitive of the real registration sequence.

  # Register bootstrap options and grab their default values for use in subsequent registration.
  GlobalOptionsRegistrar.register_bootstrap_options(register_func(GLOBAL_SCOPE))
  bootstrap_option_values = create_option_values(all_options[GLOBAL_SCOPE].copy())

  # Now register the full global scope options.
  GlobalOptionsRegistrar.register_options(register_func(GLOBAL_SCOPE))

  for optionable in optionables:
    optionable.register_options(register_func(optionable.options_scope))

  # Make inner scopes inherit option values from their enclosing scopes.
  all_scopes = set(all_options.keys())

  # TODO(John Sirois): Kill extra scopes one this goes in:
  #   https://github.com/pantsbuild/pants/issues/1957
  # For now we need a way for users of this utility to provide extra derived scopes out of band.
  # With #1957 resolved, the extra scopes will be embedded in the Optionable's option_scope
  # directly.
  if extra_scopes:
    all_scopes.update(extra_scopes)

  all_scopes = complete_scopes(all_scopes)

  # We need to update options before completing them based on inner/outer relation.
  if options:
    for scope, opts in options.items():
      all_options[scope].update(opts)

  # Iterating in sorted order guarantees that we see outer scopes before inner scopes,
  # and therefore only have to inherit from our immediately enclosing scope.
  for s in sorted(all_scopes):
    if s != GLOBAL_SCOPE:
      scope = enclosing_scope(s)
      opts = all_options[s]
      for key, val in all_options.get(scope, {}).items():
        if key not in opts:  # Inner scope values override the inherited ones.
          opts[key] = val

  return create_options(all_options)
