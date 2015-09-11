# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import copy


class RankedValue(object):
  """An option value, together with a rank inferred from its source.

  Allows us to control which source wins: e.g., a command-line flag overrides an environment
  variable which overrides a config, etc. For example:

  Consider this config:

  [compile.java]
  foo: 11

  And this environment variable:

  PANTS_COMPILE_FOO: 22

 If the command-line is

  ./pants compile target

  we expect the value of foo in the compile.java scope to be 22, because it was explicitly
  set by the user in the enclosing compile scope. I.e., the outer scope's environment value
  overrides the inner scope's config value.

  However if the command-line is

  ./pants compile.java --foo=33 target

  we now expect the value of foo in the compile.java to be 33. I.e., the inner scope's flag
  overrides the outer scope's environment value.

  To tell these cases apart we need to know the "ranking" of the value.
  """

  # The ranked value sources. Higher ranks override lower ones.
  NONE = 0  # The value None.
  HARDCODED = 1  # The default provided at option registration.
  CONFIG = 2  # The value from the config file.
  ENVIRONMENT = 3  # The value from the appropriately-named environment variable.
  FLAG = 4  # The value from the appropriately-named command-line flag.

  _RANK_NAMES = {
    NONE: 'NONE',
    HARDCODED: 'HARDCODED',
    CONFIG: 'CONFIG',
    ENVIRONMENT: 'ENVIRONMENT',
    FLAG: 'FLAG'
  }

  @classmethod
  def get_rank_name(cls, rank):
    """Returns the string name for the given rank integer.

    :param int rank: the integer rank constant (E.g., RankedValue.HARDCODED).
    :returns: the string name of the rank.
    :rtype: string
    """
    return cls._RANK_NAMES.get(rank, 'UNKNOWN')

  @classmethod
  def get_rank_value(cls, name):
    """Returns the integer constant value for the given rank name.

    :param string rank: the string rank name (E.g., 'HARDCODED').
    :returns: the integer constant value of the rank.
    :rtype: int
    """
    if name in cls._RANK_NAMES.values():
      return getattr(cls, name, None)
    return None

  @classmethod
  def get_names(cls):
    """Returns the list of rank names.

    :returns: the rank names as a list (I.e., ['NONE', 'HARDCODED', 'CONFIG', ...])
    :rtype: list
    """
    return sorted(cls._RANK_NAMES.values(), key=cls.get_rank_value)

  @classmethod
  def prioritized_iter(cls, flag_val, env_val, config_val, hardcoded_val, default):
    """Yield the non-None values from highest-ranked to lowest, wrapped in RankedValue instances."""
    if flag_val is not None:
      yield RankedValue(cls.FLAG, flag_val)
    if env_val is not None:
      yield RankedValue(cls.ENVIRONMENT, env_val)
    if config_val is not None:
      yield RankedValue(cls.CONFIG, config_val)
    if hardcoded_val is not None:
      yield RankedValue(cls.HARDCODED, hardcoded_val)
    yield RankedValue(cls.NONE, default)

  @classmethod
  def choose(cls, flag_val, env_val, config_val, hardcoded_val, default):
    """Return the highest-ranked non-None value, wrapped in a RankedValue instance."""
    for value in cls.prioritized_iter(flag_val, env_val, config_val, hardcoded_val, default):
      return value # Just return the first value.

  def __init__(self, rank, value):
    self._rank = rank
    self._value = value

  @property
  def rank(self):
    return self._rank

  @property
  def value(self):
    return self._value

  def __copy__(self):
    # The only time copy.copy() is called on a RankedValue is when the action is 'append', in which
    # case argparse copies the default value (which will be a RankedValue wrapping a list), appends
    # to it, and then sets the copy as the new value.
    # We expect argparse to set regular values, not RankedValue instances, so we return a copy of
    # the underlying list here.
    return copy.copy(self._value)

  def __eq__(self, other):
    return self._rank == other._rank and self._value == other._value

  def __repr__(self):
    return '({0}, {1})'.format(self.get_rank_name(self._rank), self._value)
